"""自检与单点查询：`doctor` / `config` / `stat`。"""

from __future__ import annotations

import argparse
from pathlib import Path

from pathlib import Path
from ... import config as config_module
from ... import paths
from ...sources import actionsets
from ...sources import graph as graph_module
from ...sources.knowledge import KnowledgeError, load_routes, load_structure_maps, probabilities_table
from ...stats import store as stats_store
from ...stats.model import StatError
from ...stats.resolver import StatQuery, StatResolver

from ..common import graph_path, print_json, stats_path




def cmd_config(args: argparse.Namespace) -> int:
    """显示固定的项目目录与配置给出的上游目录。配置缺失时由 `main` 报错退出。"""
    file = config_module.find_config()

    def describe(values: dict) -> dict:
        return {
            key: {"path": str(value), "exists": value.exists()}
            for key, value in values.items()
        }

    payload = {
        "config_file": None if file is None else str(file),
        "config_template": str(paths.ROOT / "config.example.yml"),
        "fixed": describe(paths.FIXED_ROOTS),
        "configured": describe(paths.roots()),
        "resolution": paths.summary(args.pack),
    }
    print_json(payload)
    return 0



def cmd_doctor(args: argparse.Namespace) -> int:
    args.label = args.label or args.pack
    checks: list[tuple[str, bool, str]] = []

    path = graph_path(args.label, args.graph)
    try:
        graph = graph_module.load(path)
        checks.append(("upstream", True, f"{len(graph.rules)} 条规则，{graph.label}"))
    except graph_module.GraphError as exc:
        checks.append(("upstream", False, str(exc)))

    snapshot = stats_path(args.pack, args.stats)
    try:
        store = stats_store.load(snapshot)
        packs = ", ".join(sorted(store.pack_versions()))
        checks.append(("stats", True, f"{len(store.rows)} 行，pack={packs}"))
        parents = store.check_parents()
        if parents:
            checks.append(("stats-parents", False, f"{len(parents)} 条 parent_scope 悬空"))
        else:
            checks.append(("stats-parents", True, "回退链完整"))
    except StatError as exc:
        checks.append(("stats", False, str(exc)))

    try:
        probabilities = probabilities_table()
        checks.append(("probabilities", True, f"{len(probabilities)} 条"))
    except KnowledgeError as exc:
        checks.append(("probabilities", False, str(exc)))

    try:
        routes = load_routes(Path(args.knowledge) / "routes.toml")
        checks.append(
            (
                "routes",
                True,
                f"{len(routes.underground_blocks)} 个地下方块，"
                f"{len(routes.underground_block_prefixes)} 个前缀，"
                f"{len(routes.underground_structure_prefixes)} 个地下结构前缀，"
                f"{len(routes.dimension_keywords)} 个维度",
            )
        )
    except KnowledgeError as exc:
        checks.append(("routes", False, str(exc)))

    # 数据来源：运行态只读 data/，缺失即 MISSING，没有上游回退。
    resolved = paths.summary(args.pack)
    layer_note = "；".join(
        f"{name}={item['layer']}" for name, item in resolved["sources"].items()
    )
    checks.append(
        (
            "data-sources",
            resolved["fully_local"],
            ("全部自持 data/" if resolved["fully_local"] else "缺本地快照，先跑 `bg data sync`")
            + f"（{layer_note}）",
        )
    )

    try:
        structures = load_structure_maps(Path(args.knowledge) / "structure_sets.toml")
        sets = {set_id for _, set_id in structures.loot_prefixes}
        checks.append(
            ("structures", True, f"{len(structures.loot_prefixes)} 条前缀 → {len(sets)} 个结构集合")
        )
    except KnowledgeError as exc:
        checks.append(("structures", False, str(exc)))

    # 动作图的前置完整性：前置指向一个不存在的物品时，分层会把它判成 `no_rule`
    # 并静默丢弃——那类 bug（工具名拼错、上游新增需求未接）只能在构建时记账。
    try:
        actions_file = actionsets.read(actionsets.default_path(args.pack))
    except actionsets.ActionsFileMissing:
        checks.append(("actions", True, "尚未构建（先跑 `bg index actions`）"))
    except actionsets.ActionsFileError as exc:
        checks.append(("actions", False, str(exc)))
    else:
        missing = actions_file.missing_prereqs
        total = sum(missing.values())
        if total:
            sample = "、".join(f"{name}×{count}" for name, count in list(missing.items())[:5])
            affected = sum(
                any(req.item in missing for req in action.requires)
                for action in actions_file.actionset.actions
            )
            checks.append(("actions", False, f"{affected} actions miss {len(missing)} prerequisite items, {total} references: {sample}"))
        else:
            checks.append(
                ("actions", True, f"{len(actions_file.actionset.actions)} 个动作，前置完整")
            )

    failures = [item for item in checks if not item[1]]
    for name, ok, detail in checks:
        if ok:
            print(f"OK   {name:<16}{detail}")
        else:
            print(f"FAIL {name:<16}{detail}")
    print(f"问题数：{len(failures)}")
    return 1 if failures else 0



def cmd_stats_resolve(args: argparse.Namespace) -> int:
    store = stats_store.load(stats_path(args.pack, args.stats))
    resolver = StatResolver(store)
    query = StatQuery(
        pack_version=args.pack,
        stat_type=args.stat,
        dimension=args.dimension or "",
        biome=args.biome or "",
        subject=args.subject or "",
        condition=args.condition or "",
    )
    try:
        resolved = resolver.resolve(query)
    except StatError as exc:
        print_json({"error": str(exc)})
        return 1
    print_json(resolved.as_dict())
    return 0
