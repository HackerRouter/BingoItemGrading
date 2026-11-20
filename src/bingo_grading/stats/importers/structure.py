"""结构内容统计：模板（SNBT）优先，采集侧实测兜底。

## 为什么这个优先级

模板是**静态真值**：`template_containers.jsonl` 与 `template_blocks.jsonl` 直接来自
结构文件的方块与方块实体，一个箱子挂在哪个坐标、用哪张表，没有估计成分。
采集侧扫描是**运行时实测**：能回答「一个实例实际拼了几段、几个箱子」，但样本受
世界大小与种子影响，且只能看到已生成的那一份。

所以：**内容（有哪些表、哪些方块）以模板为准；模板没有的结构才用实测补**，
典型是地牢（monster room）——它不是 jigsaw 结构，没有模板，只能实测。

两者都写，用 `condition` 区分（`source=template` / `source=measured`），
下游按优先级取：先找 template，没有再找 measured。

## 口径

| source | `containers` | `loot_tables` | 说明 |
|---|---|---|---|
| `template` | 每个模板平均容器数 | 每个模板平均表数 | 分母是该结构的模板总数，不是实例数 |
| `measured` | 每个起点平均容器数 | 每个起点平均表数 | 分母是该结构的起点（实例）数 |

两者**不可混用**：一个实例由多个模板拼成，模板平均值不是实例平均值。
把模板平均值当实例值会系统性低估（村庄一个实例有十几个片段）。

## 已知限制

- 模板侧不模拟 jigsaw 拼装，所以给不出「每实例多少」；这是采集侧的职责。
- 实测侧不区分自然地形与结构方块（`blocks` 是包围盒内的全部方块），
  所以结构专有方块只能用模板侧的 `blocks`。
- 结构会重叠，实测侧重叠处各自计入。当前不修正。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..model import WorldStat

INDEX = "structure-interior.json"
PATTERN = "structure-interior.*.json"

STRUCTURES = "structures.jsonl"
TEMPLATE_CONTAINERS = "template_containers.jsonl"
TEMPLATE_BLOCKS = "template_blocks.jsonl"

DUNGEON_SUBJECT = "minecraft:monster_room"

CONDITION_TEMPLATE = "source=template"
CONDITION_MEASURED = "source=measured"

# 模板侧的方块清单按模板数取平均；只保留出现最多的若干种，避免行过大。
MAX_BLOCKS = 60

# 合成值与实测值的允许相对偏差。超过就算「模板内容不全」，按实例的口径改用实测。
#
# 取 20% 而不是 10%：已知的两处系统性偏差都在这个量级以内——
# 采集侧对同一实例内的重叠片段去重、而合成按片段逐个累加（偏高，如 ancient_city 1.15）；
# 结构包围盒相交时把邻近结构的容器算进来（偏低，如村庄 0.85）。两者都属「重叠不处理」
# 的已知取舍，不构成数据缺失。真正缺数据的会差到 0.3 以下（trail_ruins）。
RELIABLE_TOLERANCE = 0.2


class StructureError(ValueError):
    """结构产物不可用。"""


# ---------------------------------------------------------------- 模板侧


def read_templates(facts_dir: Path) -> tuple[list[dict], dict[str, list[dict]], dict[str, dict]]:
    """读三张导出表。

    返回 `(结构行, 模板 → 容器行, 模板 → {方块: 数量})`。缺文件时返回空。
    """
    facts_dir = Path(facts_dir)
    structures: list[dict] = []
    containers: dict[str, list[dict]] = {}
    blocks: dict[str, dict] = {}

    path = facts_dir / STRUCTURES
    if path.exists():
        structures = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    path = facts_dir / TEMPLATE_CONTAINERS
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            template = row.get("template")
            if isinstance(template, str):
                containers.setdefault(template, []).append(row)

    path = facts_dir / TEMPLATE_BLOCKS
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            template = row.get("template")
            block = row.get("block")
            if not isinstance(template, str) or not isinstance(block, str):
                continue
            bucket = blocks.setdefault(template, {})
            count = row.get("count")
            bucket[block] = bucket.get(block, 0) + (int(count) if isinstance(count, (int, float)) else 1)

    return structures, containers, blocks


def _structure_templates(row: dict) -> list[str]:
    """结构行 → 它可能出现过的模板列表（按池展开，不模拟拼装）。"""
    out: list[str] = []
    for pool in row.get("pools") or []:
        if not isinstance(pool, dict):
            continue
        for element in pool.get("templates") or []:
            if not isinstance(element, dict):
                continue
            template = element.get("template")
            if isinstance(template, str):
                out.append(template)
    return list(dict.fromkeys(out))


def _local(template: str) -> str:
    """`minecraft:village/plains/houses/a` → `village/plains/houses/a`。

    采集侧报的是带命名空间的模板 ID，模板清单里是不带的。\n    """
    return template.split(":", 1)[-1]


def build_templates(
    structures: list[dict],
    containers: dict[str, list[dict]],
    blocks: dict[str, dict],
    *,
    pack_version: str,
    provenance: str = "",
    pieces: dict[str, float] | None = None,
    piece_counts: dict[str, dict[str, float]] | None = None,
) -> tuple[list[WorldStat], dict]:
    """模板内容 → 每个结构的统计行。

    行里同时有两层：

    1. **内容身份**：`templates`（可能出现的模板数）、`loot_tables` / `blocks`（每模板平均），
       用来判「这个结构里可能出现哪些表与方块」。
    2. **每实例产出**：给了 `piece_counts`（采集侧实测的「每个实例里每种模板出现几次」）时，
       按实际使用频率加权：`Σ_模板 (每实例次数 × 每模板内容)`。这是精确口径，
       与实测的 `containers_per_start` 可以互相校验。
    """
    rows: list[WorldStat] = []
    report: dict = {"structures": 0, "with_containers": 0, "without_templates": []}

    for item in structures:
        subject = item.get("structure")
        if not isinstance(subject, str):
            continue
        templates = _structure_templates(item)
        if not templates:
            report["without_templates"].append(subject)
            continue

        container_count = 0
        table_counts: dict[str, int] = {}
        block_totals: dict[str, int] = {}
        with_containers = 0

        for template in templates:
            found = containers.get(template) or []
            if found:
                with_containers += 1
                container_count += len(found)
                for cell in found:
                    table = cell.get("table")
                    if isinstance(table, str):
                        table_counts[table] = table_counts.get(table, 0) + 1
            for block, count in (blocks.get(template) or {}).items():
                block_totals[block] = block_totals.get(block, 0) + count

        total = len(templates)
        value: dict = {
            "source": "template",
            "containers": round(container_count / total, 4),
            "loot_tables": {
                table: round(count / total, 4) for table, count in sorted(table_counts.items())
            },
            "templates": total,
            "templates_with_containers": with_containers,
        }
        top_blocks = sorted(block_totals.items(), key=lambda pair: (-pair[1], pair[0]))[:MAX_BLOCKS]
        if top_blocks:
            value["blocks"] = {
                block: round(count / total, 4) for block, count in sorted(top_blocks)
            }
        per_start_pieces = (pieces or {}).get(subject)
        if isinstance(per_start_pieces, (int, float)) and per_start_pieces > 0:
            value["pieces_per_start"] = round(float(per_start_pieces), 4)

        counts = (piece_counts or {}).get(subject) or {}
        if counts:
            composed_containers = 0.0
            composed_tables: dict[str, float] = {}
            composed_blocks: dict[str, float] = {}
            for template, occurrences in counts.items():
                cells = containers.get(template) or []
                for cell in cells:
                    # 处理器型条目（带 `limit`）一行代表「本次片段放置最多替换 N 个方块」，
                    # 不是一个方块——trail_ruins 的可刷扫点全走这条路。按行数算会少 3.75 倍。
                    #
                    # 作用域是**单个 piece**：`CappedProcessor.finalizeProcessing` 里
                    # `maxToReplace = min(limit.sample(random), processedBlockInfoList.size())`，
                    # 每次拼一个 piece 调用一次、类里没有跨调用计数器。所以
                    # `每实例次数 × limit` 是正确口径；同时它还被该 piece 的方块数封顶，
                    # 候选方块不够时替换不满，这就是合成值略高于实测（1.13）的原因。
                    amount = cell.get("limit")
                    weight = float(amount) if isinstance(amount, (int, float)) else 1.0
                    composed_containers += occurrences * weight
                    table = cell.get("table")
                    if isinstance(table, str):
                        composed_tables[table] = composed_tables.get(table, 0.0) + occurrences * weight
                for block, amount in (blocks.get(template) or {}).items():
                    composed_blocks[block] = composed_blocks.get(block, 0.0) + occurrences * amount
            value["templates_placed"] = len(counts)
            value["templates_matched"] = len(
                [name for name in counts if name in blocks or name in containers]
            )
            value["containers_per_start"] = round(composed_containers, 4)
            value["loot_tables_per_start"] = {
                table: round(amount, 4) for table, amount in sorted(composed_tables.items())
            }
            top = sorted(composed_blocks.items(), key=lambda pair: (-pair[1], pair[0]))[:MAX_BLOCKS]
            if top:
                value["blocks_per_start"] = {
                    block: round(amount, 4) for block, amount in sorted(top)
                }

        rows.append(
            WorldStat(
                pack_version=pack_version,
                scope_level="global",
                dimension="",
                biome="",
                stat_type="structure_content",
                subject=subject,
                condition=CONDITION_TEMPLATE,
                value=value,
                sample_size=total,
                confidence="high",
                derived_from=("template.containers", "template.blocks"),
                provenance=provenance,
                note=(
                    "来自结构模板（SNBT）的静态真值；分母是该结构的模板总数，"
                    "不是实例数——一个实例由多个模板拼成"
                ),
            )
        )
        report["structures"] += 1
        if with_containers:
            report["with_containers"] += 1

    return rows, report


# ---------------------------------------------------------------- 实测侧


def dimension_payloads(run_dir: Path) -> dict[str, dict]:
    """`维度 → result[维度]`。缺产物时返回空字典（不静默当成 0）。"""
    return _read_run(run_dir)[0]


def dimension_ranges(run_dir: Path) -> dict[str, dict]:
    """`维度 → 该维度的采样范围`（含 `chunksScanned`）。

    算「密度 → 期望最近距离」时，分母必须是这个 `chunksScanned`。
    `result[维度]` 里的 `chunks` 是另一个口径（不是扫描范围），拿它算密度会
    把最近距离算小一大截。
    """
    return _read_run(run_dir)[1]


def _read_run(run_dir: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    """一次读完：`(维度 → result[维度], 维度 → rangeByDimension)`。"""
    run_dir = Path(run_dir)
    payloads: dict[str, dict] = {}
    ranges: dict[str, dict] = {}
    if not run_dir.is_dir():
        return payloads, ranges

    index_path = run_dir / INDEX
    files: list[Path] = []
    if index_path.exists():
        doc = json.loads(index_path.read_text(encoding="utf-8"))
        if doc.get("ok") is False:
            raise StructureError(f"{index_path} 标记 ok=false")
        for name in (doc.get("resultFiles") or {}).values():
            if isinstance(name, str):
                candidate = run_dir / name
                if candidate.exists():
                    files.append(candidate)
        for dimension, payload in (doc.get("result") or {}).items():
            if isinstance(payload, dict):
                payloads[dimension] = payload

    if not files:
        files = [path for path in sorted(run_dir.glob(PATTERN)) if path.name != INDEX]

    for path in files:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("ok") is False:
            raise StructureError(f"{path} 标记 ok=false")
        for dimension, payload in (doc.get("result") or {}).items():
            if isinstance(payload, dict):
                payloads[dimension] = payload
        for dimension, scope in (doc.get("rangeByDimension") or {}).items():
            if isinstance(scope, dict):
                ranges.setdefault(dimension, scope)
    return payloads, ranges


def _per(counts: dict, total: int) -> dict[str, float]:
    if not total:
        return {}
    return {
        key: round(float(value) / total, 4)
        for key, value in sorted(counts.items())
        if isinstance(value, (int, float)) and value
    }


def _confidence(starts: int, containers: float = 0.0) -> str:
    """样本可信度。

    不只看实例数：稀有结构（林地府邸 4 个、海底神殿 5 个、女巫小屋 4 个）
    永远达不到大样本，但它们每个实例有几十个容器，能观测到的「东西」其实不少。
    所以加一条按**容器总量**的判据——与 ADR 0019「按方块数而不是区块数判密度
    可用性」同一思路：决定估计误差的是「数到了多少」，不是「分成几堆数到」。

    两条判据取较优者：`containers >= 50` 堪比 `starts >= 30`。
    """
    if containers >= 50 or starts >= 30:
        return "high"
    if containers >= 10 or starts >= 5:
        return "medium"
    return "low"


def build_measured(
    *,
    run_dir: Path,
    pack_version: str,
    skip: frozenset[str] = frozenset(),
    provenance: str = "",
) -> tuple[list[WorldStat], dict]:
    """采集侧实测。`skip` 里的 subject 已经有模板数据，按优先级不再出实测行。"""
    rows: list[WorldStat] = []
    report: dict = {"dimensions": {}, "structures": 0, "dungeons": 0, "skipped": 0}

    payloads, ranges = _read_run(run_dir)
    for dimension, payload in sorted(payloads.items()):
        structures = payload.get("structures") or []
        report["dimensions"][dimension] = len(structures)
        # 采集器自己的区块分母：优先用 `rangeByDimension[维度].chunksScanned`，
        # 那是「本维度扫了多少区块」的权威定义。`payload["chunks"]` 是另一个口径，
        # 只在拿不到 range 时兜底。下游算「密度 → 期望最近距离」必须用它。
        scope = ranges.get(dimension) or {}
        scanned_chunks = scope.get("chunksScanned") or payload.get("chunks")

        for item in structures:
            if not isinstance(item, dict):
                continue
            subject = item.get("structure")
            starts = item.get("starts")
            if not isinstance(subject, str) or not isinstance(starts, int) or not starts:
                continue
            if subject in skip:
                report["skipped"] += 1
                continue

            containers = sum((item.get("containers") or {}).values())
            value: dict = {
                "source": "measured",
                "containers": round(float(containers) / starts, 4),
                "loot_tables": _per(item.get("lootTables") or {}, starts),
                "starts": starts,
            }
            # 「游荡撞见」口径：分母是结构覆盖的区块，不是专程去一次的起点数。
            # 与 `containers` 相差每处平均覆盖的区块数倍，两个不能互换——
            # 开箱路线用哪个取决于玩家是专程去还是路过。
            per_chunk = item.get("containersPerCoveredChunk")
            if isinstance(per_chunk, (int, float)):
                value["containers_per_covered_chunk"] = round(float(per_chunk), 6)
            if isinstance(scanned_chunks, int) and scanned_chunks:
                value["chunks"] = scanned_chunks
            for key, target in (
                ("piecesPerStart", "pieces_per_start"),
                ("volumePerStart", "volume_per_start"),
            ):
                amount = item.get(key)
                if isinstance(amount, (int, float)):
                    value[target] = round(float(amount), 4)
            for source, target in (
                ("spawners", "spawners_per_start"),
                ("entities", "entities_per_start"),
                ("blocks", "blocks_per_start"),
            ):
                per_start = _per(item.get(source) or {}, starts)
                if per_start:
                    value[target] = per_start
            # `spawnedPerStart` 已经是「每处几个」（采集侧拿 `spawnedTotal / starts` 算好再写出），
            # 再除一次 starts 会把海底神殿的 3 只变成 0.3 只，代价凭空乘十倍。
            spawned = item.get("spawnedPerStart")
            if isinstance(spawned, dict):
                per_start_spawned = {
                    key: round(float(amount), 4)
                    for key, amount in sorted(spawned.items())
                    if isinstance(amount, (int, float)) and amount > 0
                }
                if per_start_spawned:
                    value["spawned_per_start"] = per_start_spawned

            # 刷怪笼的「上限」类参数：SpawnCount / MaxNearbyEntities / SpawnRange。
            # 是实测区间（不是速率），下游用来判断刷怪笼的产能上限。
            caps = item.get("spawnerCaps")
            if isinstance(caps, dict) and caps:
                value["spawner_caps"] = caps

            rows.append(
                WorldStat(
                    pack_version=pack_version,
                    scope_level="dimension",
                    dimension=dimension,
                    biome="",
                    stat_type="structure_content",
                    subject=subject,
                    condition=CONDITION_MEASURED,
                    value=value,
                    sample_size=starts,
                    confidence=_confidence(starts, containers),
                    derived_from=("structure.starts", "structure.BB"),
                    provenance=provenance,
                    note=(
                        "采集侧实测：每起点平均；`blocks` 是包围盒内的全部方块（含自然地形），"
                        "结构专有方块要看模板行"
                    ),
                )
            )
            report["structures"] += 1

        dungeons = payload.get("dungeons") or {}
        count = dungeons.get("count")
        if isinstance(count, int) and count:
            value = {
                "source": "measured",
                "containers": round(float(dungeons.get("containersPerDungeon") or 0.0), 4),
                "loot_tables": _per(dungeons.get("lootTables") or {}, count),
                "starts": count,
            }
            if isinstance(scanned_chunks, int) and scanned_chunks:
                value["chunks"] = scanned_chunks
            if isinstance(dungeons.get("byKind"), dict):
                value["kinds"] = dict(dungeons["byKind"])
            # 地牢按锚点高度拆成 shallow（y>=0）/ deep（y<0）。下游算搜索成本时
            # 分子只能取浅层洞穴体积，所以必须知道两组各有多少间，不能拿总数。
            by_depth = dungeons.get("byDepth")
            if isinstance(by_depth, dict) and by_depth:
                value["by_depth"] = {
                    name: {
                        "count": layer.get("count"),
                        "containers_per_dungeon": round(
                            float(layer.get("containersPerDungeon") or 0.0), 4
                        ),
                    }
                    for name, layer in by_depth.items()
                    if isinstance(layer, dict)
                }
            rows.append(
                WorldStat(
                    pack_version=pack_version,
                    scope_level="dimension",
                    dimension=dimension,
                    biome="",
                    stat_type="structure_content",
                    subject=DUNGEON_SUBJECT,
                    condition=CONDITION_MEASURED,
                    value=value,
                    sample_size=count,
                    confidence=_confidence(count),
                    derived_from=("spawner.anchor", "container.bbox"),
                    provenance=provenance,
                    note=(
                        "地牢（monster room）不是 jigsaw 结构、没有模板，只能实测；"
                        "以结构外的刷怪笼为锚点聚合，starts 是间数"
                    ),
                )
            )
            report["dungeons"] += 1

    return rows, report


def _measured_spawner_extras(run_dir: Path) -> dict[str, dict]:
    """实测里模板给不出来的字段：每一处有几个刷怪笼、几只已生成实体。

    模板是**方块统计**，看不到实体与刷怪笼；所以「模板可信」只说明
    方块与容器的口径不用实测值，不等于这些结构没有实测独有信息。
    这些字段由 `build()` 并进同名的模板行，避免同一结构出现两行。
    """
    extras: dict[str, dict] = {}
    for payload in dimension_payloads(run_dir).values():
        for item in payload.get("structures") or []:
            if not isinstance(item, dict):
                continue
            subject = item.get("structure")
            starts = item.get("starts")
            if not isinstance(subject, str) or not isinstance(starts, int) or not starts:
                continue
            extra: dict = {}
            for source, target in (
                ("spawners", "spawners_per_start"),
                ("entities", "entities_per_start"),
            ):
                per_start = _per(item.get(source) or {}, starts)
                if per_start:
                    extra[target] = per_start
            # `spawnedPerStart` 已是每处量（见 `build_measured` 里的说明）。
            spawned = item.get("spawnedPerStart")
            if isinstance(spawned, dict):
                per_start_spawned = {
                    key: round(float(amount), 4)
                    for key, amount in sorted(spawned.items())
                    if isinstance(amount, (int, float)) and amount > 0
                }
                if per_start_spawned:
                    extra["spawned_per_start"] = per_start_spawned
            caps = item.get("spawnerCaps")
            if isinstance(caps, dict) and caps:
                extra["spawner_caps"] = caps
            if extra:
                extras.setdefault(subject, {}).update(extra)
    return extras


# ---------------------------------------------------------------- 合并


def build(
    *,
    run_dir: Path,
    facts_dir: Path | None = None,
    pack_version: str,
    provenance: str = "",
) -> tuple[list[WorldStat], dict]:
    """模板优先，实测兜底。返回 `(行, 报告)`。

    报告里的 `composition` 是**诊断**：把模板的「每模板平均」乘上实测的
    「每实例片段数」，与实测的「每实例容器数」对比。两者差得多说明模板集合的
    等权平均不能当「每片段实际构成」用——要精确，需要采集侧按模板（`TPL`）
    报片段分布。
    """
    rows: list[WorldStat] = []
    report: dict = {}

    measured_payloads = dimension_payloads(run_dir)
    pieces: dict[str, float] = {}
    piece_counts: dict[str, dict[str, float]] = {}
    measured_containers: dict[str, float] = {}
    for payload in measured_payloads.values():
        for item in payload.get("structures") or []:
            if not isinstance(item, dict):
                continue
            subject = item.get("structure")
            starts = item.get("starts")
            per_start = item.get("piecesPerStart")
            if not isinstance(subject, str) or not isinstance(starts, int) or not starts:
                continue
            if isinstance(per_start, (int, float)):
                pieces[subject] = float(per_start)
            counts: dict[str, float] = {}
            for entry in item.get("templates") or []:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("template")
                occurrences = entry.get("perStart")
                if isinstance(name, str) and isinstance(occurrences, (int, float)):
                    counts[_local(name)] = counts.get(_local(name), 0.0) + float(occurrences)
            if counts:
                piece_counts[subject] = counts
            # 合成侧只统计「带战利品表的容器」，所以对照也要用 lootTables，
            # 不能用 containers：后者包含熔炉、酿造台、烟炉这些工作方块，它们没有表。
            tables = sum((item.get("lootTables") or {}).values())
            measured_containers[subject] = float(tables) / starts

    # 模板内容可信（合成与实测一致）的结构。只有它们跳过实测行。
    reliable: set[str] = set()
    if facts_dir is not None and Path(facts_dir).is_dir():
        structures, containers, blocks = read_templates(Path(facts_dir))
        template_rows, template_report = build_templates(
            structures,
            containers,
            blocks,
            pack_version=pack_version,
            provenance=f"template:{Path(facts_dir).name}",
            pieces=pieces,
            piece_counts=piece_counts,
        )
        rows.extend(template_rows)
        report["template"] = template_report

        composition = []
        for row in template_rows:
            composed = row.value.get("containers_per_start")
            measured = measured_containers.get(row.subject)
            if not isinstance(composed, (int, float)) or not measured:
                continue
            ratio = float(composed) / measured if measured else None
            # 两件事分开判：
            #
            # - **容器合成值 vs 实测**：对不上说明模板池的等权平均不能当「每片段
            #   实际构成」，容器键（`containers_per_start` / `loot_tables_per_start`）
            #   不可信；
            # - **模板是否全部匹配**：`templates_matched < templates_placed` 说明
            #   有模板没在导出表里找到，方块构成本身不完整。
            #
            # 早先两者合成一个 `ok`，容器差 20% 就把 `blocks_per_start` 一起 pop
            # 掉——方块与容器没有关系，这让 `pillager_outpost` / `trial_chambers` /
            # `village_taiga` 三个变体白丢方块数据，只剩「包围盒内全部方块
            # （含地形）」的实测行可用。
            containers_ok = ratio is not None and abs(ratio - 1.0) <= RELIABLE_TOLERANCE
            templates_ok = row.value.get("templates_matched") == row.value.get("templates_placed")
            ok = containers_ok and templates_ok
            composition.append(
                {
                    "structure": row.subject,
                    "templates_placed": row.value.get("templates_placed"),
                    "templates_matched": row.value.get("templates_matched"),
                    "composed_per_start": round(float(composed), 3),
                    "measured_per_start": round(measured, 3),
                    "ratio": round(ratio, 3) if ratio is not None else None,
                    "containers_ok": containers_ok,
                    "templates_ok": templates_ok,
                    "reliable": ok,
                }
            )
            if ok:
                reliable.add(row.subject)
            if not containers_ok:
                # 合成值与实测对不上：把按实例的容器口径撤掉，避免下游拿半截数据算代价。
                for key in ("containers_per_start", "loot_tables_per_start"):
                    row.value.pop(key, None)
            if not templates_ok:
                row.value.pop("blocks_per_start", None)

        report["composition"] = sorted(composition, key=lambda item: (item["ratio"] or 0))
        report["reliable"] = sorted(reliable)
        report["unreliable"] = sorted({item["structure"] for item in composition} - reliable)

    measured_rows, measured_report = build_measured(
        run_dir=run_dir,
        pack_version=pack_version,
        skip=frozenset(reliable),
        provenance=f"structure-interior:{Path(run_dir).name}",
    )
    rows.extend(measured_rows)
    report["measured"] = measured_report

    # 模板可信的结构跳过了实测行（方块/容器口径用模板），但实测里还有模板
    # 看不到的东西：刷怪笼与已生成实体。把它们并进模板行，否则 `breeze_rod`
    # 这类只靠试炼刷怪笼的物品会整条断掉。
    extras = _measured_spawner_extras(run_dir)
    merged: list[str] = []
    template_by_subject = {
        row.subject: row
        for row in rows
        if row.stat_type == "structure_content" and row.condition == CONDITION_TEMPLATE
    }
    for subject, extra in sorted(extras.items()):
        if subject not in reliable:
            continue
        row = template_by_subject.get(subject)
        if row is None:
            continue
        row.value.update(extra)
        merged.append(subject)
    report["merged_measured"] = merged

    report["rows"] = len(rows)
    return rows, report
