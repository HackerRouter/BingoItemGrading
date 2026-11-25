"""求解类命令：`grade` / `plan` / `observe` / `mining`。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pathlib import Path
from ...case.context import CaseContext, CaseError
from ...case.registry import builder_for
from ...plan import PlanError, SolveError, SupplyError, TierError
from ...plan import solve as solve_plan
from ...plan.explain import rank_paths, render as render_paths
from ...plan.frontiers import frontiers as frontier_rows
from ...route_graph_ra import write_outputs as write_route_graph
from ...mining import MiningError, estimate_from_row
from ... import grade as grade_module
from ... import observe as observe_module
from ...sources import actions as source_actions
from ...sources import actionsets
from ...sources import graph as graph_module
from ...stats import store as stats_store
from ...gamedata import MIN_DENSITY_BLOCKS

from ..common import _score, _tier, index_path, print_json, stats_path
from ..grade_table import _emit_histogram, _grade_all, _grade_items, _grade_one, _grade_solved, _grade_together, _graph_file




def cmd_mining(args: argparse.Namespace) -> int:
    """按群系求「挖到某方块」的 TU 代价。"""
    store = stats_store.load(stats_path(args.pack_version, args.stats))

    rows = [
        row
        for row in store.rows.values()
        if row.stat_type in ("ore_density", "block_density")
        and row.subject == args.subject
        and row.dimension == args.dimension
        and (not args.biome or row.biome == args.biome)
    ]
    if not rows:
        print_json(
            {
                "subject": args.subject,
                "dimension": args.dimension,
                "biome": args.biome or "*",
                "note": "没有该方块的群系级密度行；先跑 bg data ingest",
                "candidates": [],
            }
        )
        return 1

    candidates = []
    for row in sorted(rows, key=lambda item: item.biome):
        try:
            estimate = estimate_from_row(
                row,
                target_items=args.items,
                surface_y=args.surface_y,
                break_block=args.break_block,
                entries_per_block=args.entries_per_block,
            )
        except MiningError as exc:
            candidates.append({"biome": row.biome, "error": str(exc)})
            continue
        payload = estimate.as_dict()
        payload["tier"] = None if estimate.cost_tu is None else _tier(estimate.cost_tu)
        payload["score"] = None if estimate.cost_tu is None else _score(estimate.cost_tu)
        if not args.expand:
            # 默认只给结论：最优段 + 假设。全部纵段要 --expand。
            payload.pop("all_sections", None)
            if payload.get("best_section"):
                payload["best_section"].pop("volume_density", None)
        candidates.append(payload)

    usable = [item for item in candidates if item.get("cost_tu") is not None]
    # 与 DAG 案例同一规则：优先在样本够的群系里取最优，全都不够才退回全部。
    trusted = [item for item in usable if item.get("density_trusted")]
    pool = trusted or usable
    best = min(pool, key=lambda item: item["cost_tu"]) if pool else None

    output: dict = {
        "subject": args.subject,
        "dimension": args.dimension,
        "target_items": args.items,
        "best": best,
        "candidate_count": len(candidates),
        "trusted_count": len(trusted),
        "note": (
            "代价 = 到达该层 + 挖矿道；--expand 看全部纵段。"
            f"样本量判据为方块数 >= {MIN_DENSITY_BLOCKS}（见 ADR 0019）"
        ),
    }
    if args.expand:
        output["candidates"] = candidates
    else:
        output["candidates"] = [
            {
                key: item[key]
                for key in ("biome", "cost_tu", "tier", "score", "density_trusted", "sample_blocks")
                if key in item
            }
            for item in candidates
        ]
    print_json(output)
    return 0 if usable else 1



def cmd_plan(args: argparse.Namespace) -> int:
    """按供给曲线算某件物品的获得路线（含前置分层与竞争）。

    自 2026-11-12 起，任何物品都能算：动作图从来源索引自动拼，
    不再要求先在 `case/registry.py` 登记。`--index` 可指向另一份来源索引。
    """
    builder = builder_for(
        args.item,
        pack=args.pack_version,
        index_path=Path(args.index) if getattr(args, "index", None) else None,
    )

    ctx = CaseContext.load(
        stats_path(args.pack_version, args.stats), dimension=args.dimension
    )
    try:
        built = builder(ctx)
        actionset = built.actionset()
        solved = solve_plan(
            actionset,
            args.item,
            args.count,
            prune_dominated=not getattr(args, "no_prune", False),
        )
    except (CaseError, PlanError, SupplyError, TierError, SolveError) as exc:
        print_json({"item": args.item, "error": str(exc)})
        return 1

    payload = solved.as_dict(detail=args.expand)
    payload["assumptions"] = built.assumptions
    wanted = list(args.paths_item or [])
    if args.paths:
        wanted.insert(0, args.item)
    if wanted:
        trees = []
        blank = []
        for name in wanted:
            found = rank_paths(actionset, solved, name, limit=args.path_limit)
            if not found:
                blank.append(name)
            trees.extend(found)
        payload["paths"] = [tree.as_dict() for tree in trees]
        payload["paths_text"] = render_paths(trees)
        if blank:
            payload["paths_missing"] = blank
    if getattr(args, "graph_out", None):
        trees = rank_paths(
            actionset,
            solved,
            args.item,
            limit=max(1, int(getattr(args, "graph_paths", 3))),
            depth=max(1, int(getattr(args, "graph_depth", 16))),
        )
        if trees:
            rows = None
            limit = max(0, int(getattr(args, "graph_frontiers", 8)))
            if limit:
                rows = [
                    row.as_dict()
                    for row in frontier_rows(
                        actionset,
                        solved,
                        trees[0],
                        limit=limit,
                        prune_dominated=not getattr(args, "no_prune", False),
                    )
                ]
            written = write_route_graph(
                Path(args.graph_out), trees, args.item, frontiers=rows
            )
            payload["graph"] = {"out": written, "paths": len(trees)}
        else:
            payload["graph"] = {"out": [], "error": "没有可画的路线"}
    payload["provenance"] = {
        name: sourced.as_dict() for name, sourced in built.provenance.items()
    }
    frames = built.extras.get("frames") or ()
    if args.expand and frames:
        payload["frames"] = [frame.as_dict() for frame in frames]
    # 未接入来源跟着一起输出：没接上的东西必须是可见的。
    for key in (
        "uncovered",
        "uncovered_total",
        "source_records",
        "source_by_type",
        "gaps",
    ):
        if key in built.extras:
            payload[key] = built.extras[key]
    print_json(payload)
    return 0 if solved.plan.feasible else 1



def cmd_grade(args: argparse.Namespace) -> int:
    """一批物品的 Bingo 难度表。

    与 `plan` 的区别在输入形态：那个一次回答一件，
    这个回答「一张卡整体有多难，哪几件的分数不可信」。
    评分口径仍走 `bingo_grading.units.score_from_cost`，这里不另立一套。
    """
    ctx = CaseContext.load(
        stats_path(args.pack_version, args.stats), dimension=args.dimension
    )
    if getattr(args, "all", False):
        return _grade_all(ctx, args)
    items = _grade_items(args)
    if not items:
        print_json({"error": "没有目标物品：用 --item / --file 给一份清单，或 --all 算全库"})
        return 1
    if getattr(args, "together", False):
        return _grade_together(ctx, items, args)
    index_path = Path(args.index) if args.index else source_actions.default_index(
        args.pack_version
    )
    try:
        graph = _graph_file(ctx, args, index_path)
    except actionsets.ActionsFileError as exc:
        print_json({"error": str(exc)})
        return 1
    if len(items) > grade_module.JOINT_THRESHOLD:
        rows = _grade_solved(graph, items, args)
    else:
        rows = [_grade_one(graph, item, args) for item in items]
    payload = {
        "pack": args.pack_version,
        "count": args.count,
        "items": [row.as_dict() for row in rows],
        "summary": grade_module.summarize(rows),
        "table": grade_module.render_table(rows),
    }
    if args.out:
        # 中文一律由脚本自己按 UTF-8 写，不走终端重定向。
        Path(args.out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8",
        )
        payload["out"] = str(args.out)
    if getattr(args, "table_out", None):
        payload["table_out"] = [
            {"path": str(path), "format": grade_module.render_table_file(rows, path)}
            for path in args.table_out
        ]
    if getattr(args, "histogram", False) or getattr(args, "histogram_out", None):
        if len(items) > grade_module.JOINT_THRESHOLD:
            solved = solve_plan(
                graph.actionset, items[0], args.count, prune_dominated=False
            )
        else:
            solved = None
        payload["histogram"] = _emit_histogram(rows, graph.actionset, solved, args)
    if args.table:
        print(payload["table"])
    else:
        print_json(payload)
    return 0



def cmd_observe(args: argparse.Namespace) -> int:
    """摊开若干节点：最便宜段、前置花费、备选来源、另一套求解器的对照。"""
    ctx = CaseContext.load(
        stats_path(args.pack_version, args.stats), dimension=args.dimension
    )
    index_path = Path(args.index) if args.index else source_actions.default_index(
        args.pack_version
    )
    try:
        graph = _graph_file(ctx, args, index_path)
    except actionsets.ActionsFileError as exc:
        print_json({"error": str(exc)})
        return 1
    items = _grade_items(args)
    if not items:
        print_json({"error": "没有目标节点：用 --item 给一份清单"})
        return 1
    by_id = {action.action_id for action in graph.actionset.actions}
    wanted_actions = [name for name in items if name in by_id]
    wanted_items = [name for name in items if name not in by_id]
    if not wanted_items and not wanted_actions:
        print_json({"error": "清单里的名字既不是物品也不是动作"})
        return 1
    target = (
        wanted_items[0]
        if wanted_items
        else (graph.targets[0] if graph.targets else "minecraft:diamond")
    )

    try:
        solved = solve_plan(graph.actionset, target, args.count, prune_dominated=False)
    except (PlanError, SupplyError, TierError, SolveError) as exc:
        print_json({"error": str(exc)})
        return 1
    prices = observe_module.price_table(solved, args.count)
    nodes = [
        observe_module.report_node(
            graph.actionset,
            solved,
            item,
            demand=args.count,
            neighbours_of=observe_module.neighbours(prices, item, args.nearby),
        )
        for item in wanted_items
    ]
    actions = [
        observe_module.report_action(graph.actionset, solved, action_id)
        for action_id in wanted_actions
    ]
    sections = []
    if nodes:
        sections.append(observe_module.render(nodes))
    if actions:
        sections.append(observe_module.render_actions(actions))
    payload = {
        "pack": args.pack_version,
        "count": args.count,
        "solver": "dag",
        "budget": graph.budget,
        "nodes": nodes,
        "actions": actions,
        "table": "\n\n".join(sections),
    }
    if args.out:
        Path(args.out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8",
        )
        payload["out"] = str(args.out)
    if args.table:
        print(payload["table"])
    else:
        print_json(payload)
    return 0
