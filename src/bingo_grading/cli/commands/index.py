"""写入 `build/` 的命令：`sources` / `slots` / `actions`。"""

from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path

from pathlib import Path
from ...case.context import CaseContext, CaseError
from ... import paths
from ...plan import PlanError, SupplyError, TierError
from ...recipes.expand import build_index as craft_index
from ...sources import actions as source_actions
from ...sources import actionsets
from ...sources import graph as graph_module
from ...sources import index as source_index
from ...sources.drops import DropIndex
from ...sources.exposure import ExposureRoutes
from ...sources.index import build as build_sources
from ...sources.knowledge import load_routes, load_structure_maps, probabilities_table
from ...slots.build import build as build_slots
from ...slots.build import write as write_slots
from ...slots.report import item_slots, report as slot_report
from ...stats import store as stats_store

from ..common import graph_path, index_path, print_json, stats_path
from ..grade_table import _build_and_write




def cmd_graph_build(args: argparse.Namespace) -> int:
    """把全库动作图落盘，之后 `grade` 只读盘、不重建。"""
    ctx = CaseContext.load(
        stats_path(args.pack_version, args.stats), dimension=args.dimension
    )
    index_path = Path(args.index) if args.index else source_actions.default_index(
        args.pack_version
    )
    path = Path(args.out) if args.out else actionsets.default_path(args.pack_version)
    digest = actionsets.digest_inputs(
        pack=args.pack_version,
        index_path=index_path,
        stats_path=stats_path(args.pack_version, args.stats),
    )
    try:
        header = _build_and_write(ctx, args, index_path, path, digest)
    except (CaseError, PlanError, SupplyError, TierError) as exc:
        print_json({"error": str(exc)})
        return 1
    # 头部里的 `sources` / `uncovered` 各有一千多项，刷到终端没有意义。
    payload = {key: header[key] for key in (
        "actions_schema",
        "label",
        "pack_version",
        "stats_digest",
        "actions",
        "targets",
        "budget",
    )}
    payload["uncovered_total"] = sum(header["uncovered"].values())
    payload["no_action_items"] = header["no_action_items"]
    payload["no_action_examples"] = header["no_action_examples"]
    # 前置指向不存在的物品：这类动作会被分层静默丢弃，所以必须显式报出来。
    payload["missing_prereq_items"] = header.get("missing_prereq_items", 0)
    payload["missing_prereqs"] = dict(
        list(header.get("missing_prereqs", {}).items())[:10]
    )
    payload["path"] = str(path)
    print_json(payload)
    return 0



def cmd_slots(args: argparse.Namespace) -> int:
    """槽位索引：默认写盘，`--report` 或 `--item` 改为出报告。

    构建模式写 `build/<label>/slots.jsonl`（`--out` 可改路径）；
    报告模式只读不写，`--item` 时只列该物品的候选。
    """
    _, records = source_index.read(index_path(args.label, args.index))
    graph = graph_module.load(graph_path(args.label, args.graph))
    result = build_slots(records, craft=craft_index(graph), max_depth=args.max_depth)

    if not args.report and not args.item:
        out = (
            Path(args.out) if args.out else paths.BUILD_ROOT / args.label / "slots.jsonl"
        )
        write_slots(result.slots, out)
        print_json(
            {
                "items": len({slot.item for slot in result.slots}),
                "slots": len(result.slots),
                "unexpanded": len(result.unexpanded),
                "truncated": result.stats.truncated,
                "path": str(out),
            }
        )
        return 0

    if args.item:
        rows = [slot.as_dict() for slot in item_slots(result.slots, args.item)]
        if not rows:
            print_json({"item": args.item, "slots": [], "note": "no automatic candidate"})
            return 0
        print_json({"item": args.item, "slots": rows})
        return 0

    full = slot_report(result, records)
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(full, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    print_json(
        {
            "items": full["items"],
            "slots": full["slots"],
            "sources": full["sources"],
            "direct_slots": full["direct_slots"],
            "craft_slots": full["craft_slots"],
            "cells": full["cells"],
            "empty_cells": [
                f"{cell['route']}/{cell['obtain_method']}" for cell in full["empty_cells"]
            ],
            "items_without_slots": full["items_without_slots"],
            "unexpanded_count": full["unexpanded_count"],
            "unexpanded_items": full["unexpanded_items"],
            "single_route_count": full["single_route_count"],
            "craft_truncated": full["craft"]["truncated"],
            "craft_missing": full["craft"]["missing_count"],
            "craft_cycles": len(full["craft"]["cycles"]),
        }
    )
    return 0



def cmd_sources_build(args: argparse.Namespace) -> int:
    graph = graph_module.load(graph_path(args.label, args.graph))
    knowledge = Path(args.knowledge)
    probabilities = probabilities_table()
    routes = load_routes(knowledge / "routes.toml")
    structures = load_structure_maps(knowledge / "structure_sets.toml")
    # 地下结构集合写在结构映射文件里，路线规则要合并后才能用上。
    routes = dataclasses.replace(
        routes, underground_structure_sets=structures.underground_sets
    )
    # 概率优先由战利品表算出来的期望供给；统计快照缺失时退回手工表。
    drops = None
    exposure = None
    stats_file = stats_path(getattr(args, "pack_version", None) or args.label, args.stats)
    if stats_file.exists():
        store = stats_store.load(stats_file)
        drops = DropIndex.from_rows(store.rows)
        # 路线也改用实测暴露：手写的地下清单漏了 iron_ore 这类浅层矿石。
        exposure = ExposureRoutes.from_rows(store.rows)
    result = build_sources(
        graph, probabilities, routes, structures, drops=drops, exposure=exposure
    )

    out = Path(args.out) if args.out else paths.BUILD_ROOT / args.label / "source_index.jsonl"
    result.write(out)
    summary = result.summary()
    summary["path"] = str(out)
    summary["drop_index"] = len(drops) if drops is not None else None
    summary["exposure_routes"] = len(exposure) if exposure is not None else None
    summary["stats_path"] = str(stats_file)
    print_json(summary)
    return 0
