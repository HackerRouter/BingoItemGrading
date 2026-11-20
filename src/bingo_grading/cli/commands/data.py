"""写入 `data/` 的命令：`sync` / `verify` / `ingest` / `loot`。"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from collections import Counter
from pathlib import Path
from ... import paths
from ... import tags as tag_module
from ... import upstream as upstream_module
from ...loot.tables import load as load_loot_tables
from ...sources.knowledge import load_structure_maps
from ...slots.report import report as slot_report
from ...stats import store as stats_store
from ...stats.importers import loot as loot_import
from ...stats.importers import spawn as spawn_import
from ...stats.importers import structure as structure_import
from ...stats.importers import trade as trade_import
from ...stats.importers import worldgen as worldgen_import
from ...stats.model import WorldStatStore

from ..common import index_path, is_ore_subject, print_json, stats_path




def cmd_stats_import(args: argparse.Namespace) -> int:
    if args.run:
        run_dir = Path(args.run)
    elif args.collector:
        run_dir = _latest_run(Path(args.collector))
    else:
        if not args.pack:
            print("请用 --pack 指定地形包版本，或给 --run / --collector")
            return 1
        resolved = paths.collector_run(args.pack)
        if not resolved.exists:
            print(f"找不到统计运行目录：{resolved.path}")
            return 1
        run_dir = resolved.path
    pack = args.pack or worldgen_import.guess_minecraft_version(run_dir)
    if not pack:
        print("无法从 summary.json 推断版本，请显式给 --pack")
        return 1

    dimensions = [args.dimension] if args.dimension else None
    result = worldgen_import.import_run(run_dir, pack, dimensions=dimensions)

    store = WorldStatStore()
    for stat in result.rows:
        store.add(stat)

    # 结构内容：模板（SNBT）优先，采集侧实测兜底（如地牢）。
    # 三张导出表（structures / template_containers / template_blocks）从 2026-11-21 起
    # 在 `output/<pack>/export/` 下，不再散在 output 根目录。
    ra = paths.recipe_analysis(pack)
    export = paths.recipe_export(pack)
    structure_rows, structure_report = structure_import.build(
        run_dir=run_dir,
        facts_dir=export.path if export.exists else None,
        pack_version=pack,
    )
    for stat in structure_rows:
        store.add(stat)

    # 交易：职业/等级 → 报价组。`set` 层必须靠标签展开。
    trade_rows: list = []
    trade_report: dict = {"skipped": "无 trading facts"}
    trade_path = ra.path / "facts" / "trade.jsonl"
    if trade_path.exists():
        tag_resolved = paths.tag_facts(pack)
        trade_rows, trade_report = trade_import.build(
            facts_path=trade_path,
            pack_version=pack,
            tags=tag_module.load(tag_resolved.path),
            provenance=f"trade:{ra.layer}",
        )
        for stat in trade_rows:
            store.add(stat)

    # 刷怪表：静态刷怪规则（C17 撤回后用这份事实代替实测密度）。
    # 与其它导出物一起放在 `export/` 下。
    spawn_report: dict = {"skipped": "无 spawn_tables"}
    spawn_path = export.path / spawn_import.SPAWN_TABLES
    if spawn_path.exists():
        spawn_rows, spawn_report = spawn_import.build(
            tables_path=spawn_path,
            pack_version=pack,
            provenance=f"spawn_tables:{ra.layer}",
        )
        for stat in spawn_rows:
            store.add(stat)

    out = Path(args.out) if args.out else paths.STATS_ROOT / pack

    # 这个命令只重建**自己产的那些类型**（采集侧统计、结构内容、交易报价）。
    # `bg data loot` 写的 `loot_expectation` 等行必须原样留着——以前这里从头
    # 新建 store 直接覆盖整个文件，把战利品行整批冲掉，下游查不到表还以为是数据缺失。
    generated_types = {row.stat_type for row in store.rows.values()}
    preserved = 0
    if out.exists():
        try:
            previous = stats_store.load(out)
        except Exception as exc:  # 旧快照格式不符就不保留，但不能静默
            print_json({"warning": f"旧快照无法读取，未保留非本次生成的行：{exc}"})
            previous = None
        if previous is not None:
            for row in previous.rows.values():
                if row.stat_type in generated_types:
                    continue
                store.add(row)
                preserved += 1

    stats_store.dump(store, out)

    # 溯源文件：证明这批统计来自哪个地形包、哪个种子。与快照同目录。
    target_path = out / "target.json"
    target_path.write_text(
        json.dumps(result.target.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    report = result.summary()
    report["path"] = str(out)
    report["target_path"] = str(target_path)
    report["structure"] = structure_report
    report["trade"] = trade_report
    report["spawn"] = spawn_report
    report["preserved_rows"] = preserved

    if args.index:
        report["source_gaps"] = _source_gap_report(
            Path(args.index), store, pack, args.dimension or worldgen_import.DEFAULT_DIMENSION
        )

    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    print_json(report)
    return 0



def cmd_loot_build(args: argparse.Namespace) -> int:
    args.label = args.label or args.pack_version
    """解析战利品表 → `loot_expectation` 行，并入统计快照。"""
    knowledge = Path(args.knowledge)
    structures = load_structure_maps(knowledge / "structure_sets.toml")

    # 战利品表取**生效后的合并结果**：上游已按 `pack.mcmeta` 的 overlay 区间
    # 判定并逐层覆盖，产出 `datapack-merged/`，同步时落到 `data/upstream/<pack>/datapack/`。
    # 本侧不再判定 overlay、不再叠加地形包层。
    dirs: list[Path] = []
    sources: dict[str, dict] = {}
    if args.base:
        for value in args.base:
            dirs.append(Path(value))
        sources["vanilla"] = {"paths": [str(p) for p in dirs], "layer": "override"}
    else:
        merged = paths.loot_tables(args.label)
        dirs.append(merged.path)
        sources["loot_tables"] = merged.as_dict()

    tables = load_loot_tables(dirs)

    if args.templates:
        template_facts = Path(args.templates)
        template_layer = "override"
    else:
        resolved = paths.template_facts(args.label)
        template_facts = resolved.path
        template_layer = resolved.layer
    structure_loot = loot_import.read_structure_loot(template_facts, structures.set_for_template)

    store = stats_store.load(stats_path(args.pack_version, args.stats))
    provenance = f"loot:{'+'.join(str(Path(value).name) for value in dirs)}"
    # 标签表：战利品表里的 `tag` 条目要靠它展开（无数据时该条目仍按未展开计）。
    tag_resolved = paths.tag_facts(args.label)
    tags = tag_module.load(tag_resolved.path)
    rows, report = loot_import.build(
        tables=tables,
        structure_loot=structure_loot,
        pack_version=args.pack_version,
        dimension=args.dimension,
        structure_density=loot_import.density_lookup(store),
        provenance=provenance,
        tags=tags,
    )
    # 方块 / 生物 / 剪毛 / 刷扫：一次触发的期望产出。
    # 模板里已挂成箱子的表跳过，避免与上面的行同主键互覆盖。
    covered = frozenset(
        table_id for loot in structure_loot.values() for table_id in loot.table_chests
    )
    drop_rows, drop_report = loot_import.build_drops(
        tables=tables,
        pack_version=args.pack_version,
        provenance=provenance,
        skip=covered,
        tags=tags,
    )
    # `bg data loot` 是这一种 stat_type 的**全量重建**：主键含 `condition`，
    # 改了 condition 的生成规则之后旧行不会被同主键覆盖，会和新行同时留着
    # （实测 `wither_skeleton` 一度有两行 trigger=kill，一行含着已被修掉的
    # 「煤炭期望 0」）。所以先清掉本 pack 的旧行再写，保证重建后无残留。
    stale = [
        stat.key
        for stat in store.of_pack(args.pack_version)
        if stat.stat_type == "loot_expectation"
    ]
    for key in stale:
        store.remove(key)
    written = loot_import.merge_into(store, rows) + loot_import.merge_into(store, drop_rows)
    stats_store.dump(store, stats_path(args.pack_version, args.stats))

    report.update(
        {
            "tables_loaded": len(tables),
            "tables_broken": len(tables.broken),
            "structure_sets": len(structure_loot),
            "rows_written": written,
            "drops": drop_report,
            "tag_facts": {"path": str(tag_resolved.path), "tags": len(tags)},
            "stats_path": str(stats_path(args.pack_version, args.stats)),
            "sources": sources,
            "template_facts": {"path": str(template_facts), "layer": template_layer},
        }
    )
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print_json(report)
    return 0



def _latest_run(collector: Path) -> Path:
    """取最新一次统计运行目录。按目录名（ISO 时间戳）排序。"""
    if not collector.is_dir():
        raise FileNotFoundError(f"统计目录不存在：{collector}")
    runs = sorted((path for path in collector.iterdir() if path.is_dir()), key=lambda path: path.name)
    candidates = [run for run in runs if any(run.glob("*.json"))]
    if not candidates:
        raise FileNotFoundError(f"{collector} 下没有含 json 的统计运行")
    return candidates[-1]



def _source_gap_report(index_path: Path, store: WorldStatStore, pack: str, dimension: str) -> dict:
    """比较来源索引的统计键与快照里实际存在的行。

    口径分三层，避免「有映射的那部分全绿」盖住「大量来源压根没映射」：

    - `required` / `covered` / `missing`：同一统计类型的键，缺行即缺口。
    - `unmapped`：来源没有统计键（结构集合映射不到），按来源数计。
    - `no_stat_type`：该类来源第一版没有对应统计类型，不计入覆盖率。
    """
    from .sources import index as source_index_module

    _, records = source_index_module.read(index_path)

    stat_type_for = {
        "block_drop": "ore_density",
        "shear": "mob_density",
        "mob_drop": "mob_density",
        "loot_table": "structure_density",
        "suspicious_block": "structure_density",
    }
    no_stat_type = {
        "trade": "交易没有对应统计类型：交易代价由策略注册表给，不由世界统计给",
    }

    wanted: dict[str, set[str]] = {}
    unmapped: dict[str, list[str]] = {}
    unmapped_items: dict[str, set[str]] = {}
    for record in records:
        stat_type = stat_type_for.get(record.source_type)
        if stat_type is None:
            continue
        if record.stat_subject is None:
            unmapped.setdefault(record.source_type, []).append(record.subject)
            unmapped_items.setdefault(record.source_type, set()).add(record.item)
            continue
        wanted.setdefault(record.source_type, set()).add(record.stat_subject)

    gaps: dict[str, list[str]] = {}
    covered: dict[str, int] = {}
    required: dict[str, int] = {}
    # 群系级统计（ore_density / biome_patch）按「任意 scope 下有行」判定，
    # 因为它们本质上就是群系维度的量，不存在维度级版本。
    biome_level_types = {"ore_density", "biome_patch"}
    present: dict[str, set[str]] = {}
    for row in store.rows.values():
        present.setdefault(row.stat_type, set()).add(row.subject)

    for source_type, subjects in wanted.items():
        stat_type = stat_type_for[source_type]
        # 只有矿石方块才需要矿石密度：木头、按钮这类方块来源的难度
        # 走群系分布与配方链，不查矿石密度。不筛会让缺口报告虚报上千条。
        if stat_type == "ore_density":
            subjects = {subject for subject in subjects if is_ore_subject(subject)}
        if not subjects:
            continue
        required[source_type] = len(subjects)
        if stat_type in biome_level_types:
            available = present.get(stat_type, set())
            missing = sorted(subject for subject in subjects if subject not in available)
        else:
            missing = [
                subject
                for subject in sorted(subjects)
                if (pack, "dimension", dimension, "", stat_type, subject, "") not in store.rows
            ]
        covered[source_type] = len(subjects) - len(missing)
        if missing:
            gaps[source_type] = missing

    # 未映射的结构来源：有来源、但查不到统计键。按 subject 汇总后排序。
    unmapped_summary: dict[str, list[dict]] = {}
    for source_type, subjects in unmapped.items():
        counter = dict(Counter(subjects))
        unmapped_summary[source_type] = [
            {"subject": subject, "sources": count}
            for subject, count in sorted(counter.items(), key=lambda kv: -kv[1])
        ]

    return {
        "wanted": {key: len(value) for key, value in wanted.items()},
        "required": required,
        "covered": covered,
        "missing": gaps,
        "missing_counts": {key: len(value) for key, value in gaps.items()},
        "unmapped": unmapped_summary,
        "unmapped_counts": {
            key: sum(item["sources"] for item in value) for key, value in unmapped_summary.items()
        },
        "unmapped_item_counts": {
            key: len(value) for key, value in unmapped_items.items()
        },
        "no_stat_type": no_stat_type,
        "non_ore_block_sources": sum(
            1
            for record in records
            if record.source_type == "block_drop" and not is_ore_subject(record.subject)
        ),
    }



def cmd_upstream_sync(args: argparse.Namespace) -> int:
    """把上游产物与原版数据复制进 data/。

    复制之前先检查上游是否已经解包/构建过 —— `inputs/`、`.cache/server-*/structures`、
    `output/` 都不是上游仓库里常驻的目录，缺了只会让同步悄悄少一块。
    """
    missing = upstream_module.missing_prerequisites(args.pack)
    report = upstream_module.sync(args.pack, dry_run=args.dry_run)
    payload = report.as_dict()
    payload["dry_run"] = args.dry_run
    payload["prerequisites"] = [item.as_dict() for item in missing]
    if missing:
        payload["hint"] = (
            f"上游前置缺 {len(missing)} 项，同步出来的 data/ 会缺少对应部分："
            + "；".join(f"{item.key} → {item.action}" for item in missing)
        )
    if args.dry_run:
        payload["note"] = "只统计，未复制；去掉 --dry-run 才写入 data/"
    print_json(payload)
    return 0 if report.entries else 1



def cmd_upstream_verify(args: argparse.Namespace) -> int:
    """按 manifest 校验本地副本。"""
    result = upstream_module.verify(args.pack)
    print_json(result.as_dict())
    return 0 if result.ok else 1
