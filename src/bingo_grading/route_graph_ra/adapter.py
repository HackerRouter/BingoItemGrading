"""本项目的路线树 → RA 风格 `PathGraph`（item / rule 二分）。

图的形状与 RA 一致：

- **item 节点**（矩形）：一个物品。多条入边 = 同一物品的多个候选来源（OR）；
- **rule 节点**（菱形）：一条动作。多条入边 = 该动作的并列前置（AND）；
- 边一律「来源 → 产物」：`item(前置) -> rule -> item(产物)`。

B1a 只展开 `rank_paths` 已经给出的树：根级有 N 条候选，每个前置取它自己的
最优来源。前置级的候选展开留给 B1b。
"""

from __future__ import annotations

import html
import math

from ..plan.explain import PathTree, Step
from .colors import HIGHLIGHT_COLOR, cost_cap, route_color, route_ink
from .path_graph import PathGraph
from .style import short


def _item_key(item: str) -> str:
    return f"item::{item}"


def _rule_key(action_id: str) -> str:
    return f"rule::{action_id}"


def _html_text(value: str) -> str:
    return html.escape(str(value), quote=False)


def _fmt_need(need: float) -> str:
    """需求数量的显示形式。

    一次动作产出多件时，前置只需要它的几分之一（`9 个 copper_ingot` 只需
    `1/9 个 waxed_copper_block`）。`×0.111` 看不出这层意思，写成 `×1/9`。
    """
    if not need or not math.isfinite(need):
        return "×1"
    if need >= 1:
        return f"×{need:.3g}"
    inverse = 1.0 / need
    whole = round(inverse)
    if whole and abs(inverse - whole) < 1e-6:
        return f"×1/{whole}"
    return f"×{need:.3g}"


def _note(step: Step) -> str:
    """截断备注改成人话：成本已经算进去了，省掉的只是下游明细。"""
    if step.note.startswith("递归深度用尽"):
        return "展开到深度上限，成本已计入"
    return step.note


def _node_label(step: Step) -> str:
    """动作节点：名称 / 描述 / `单价 TU × 需要量`，HTML table 控制行距。"""
    title = step.action_id.replace("minecraft:", "") if step.action_id else short(step.item)
    lines = [title]
    if step.label:
        head = step.label.split("（", 1)[0].strip().replace("minecraft:", "")
        if head:
            lines.append(head[:48] + ("…" if len(head) > 48 else ""))
    if step.unit_cost and math.isfinite(step.unit_cost):
        lines.append(f"{step.unit_cost:.2f} TU {_fmt_need(step.need)}")
    if step.note:
        lines.append(_note(step))
    rows = "".join(f"<TR><TD>{_html_text(line)}</TD></TR>" for line in lines)
    return (
        '<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="3">'
        + rows
        + "</TABLE>"
    )


def _tooltip(step: Step) -> str:
    pieces = [
        f"动作：{step.action_id or '（无）'}",
        f"物品：{step.item}",
        f"单价：{step.unit_cost:.4g} TU",
        f"需求：{step.need:g}",
        f"调用：{step.calls:g}",
        f"小计：{step.subtotal:.4g} TU",
    ]
    if step.source:
        pieces.append(f"来源：{step.source}")
    if step.label:
        pieces.append(step.label)
    if step.note:
        pieces.append(f"备注：{_note(step)}")
    return "；".join(pieces)


def to_path_graph(
    trees: list[PathTree], target: str, *, rankdir: str = "TB"
) -> PathGraph:
    """把前 N 条路线转成一张 item / rule 图。"""
    graph = PathGraph(target=_item_key(target))
    graph.nodes[graph.target] = {"label": short(target), "sort": "item"}
    best = min((tree.total_cost for tree in trees if tree.total_cost > 0), default=0.0)
    cap = cost_cap(trees, best)
    node_ratio: dict[str, float] = {}
    edge_ratio: dict[tuple[str, str, str], float] = {}

    def add_item(item: str, ratio: float, best: bool) -> str:
        key = _item_key(item)
        info = graph.nodes.setdefault(
            key,
            {"label": short(item), "sort": "item", "tooltip": item},
        )
        if key not in node_ratio or ratio < node_ratio[key]:
            node_ratio[key] = ratio
            info["border"] = HIGHLIGHT_COLOR if best else route_color(ratio, cap)
        return key

    def add_edge(
        source: str,
        destination: str,
        tag: str,
        label: str,
        tooltip: str,
        ratio: float,
        color: str,
        *,
        dashed: bool = False,
    ) -> None:
        key = (source, destination, tag)
        if key in edge_ratio and ratio >= edge_ratio[key]:
            return
        edge_ratio[key] = ratio
        graph.edges[key] = (label, tooltip)
        graph.edge_colors[key] = color
        if dashed:
            graph.dashed.add(key)
        else:
            graph.dashed.discard(key)

    def emit(
        step: Step,
        ratio: float,
        *,
        root: bool = False,
        best: bool = False,
        total: float = 0.0,
    ) -> None:
        color = HIGHLIGHT_COLOR if best else route_color(ratio, cap)
        rule_key = _rule_key(step.action_id or f"{step.item}@{id(step)}")
        info = graph.nodes.setdefault(
            rule_key,
            {
                "label": _node_label(step),
                "html": True,
                "sort": "rule",
                "tooltip": _tooltip(step),
            },
        )
        if step.note:
            info["cut"] = True
        if rule_key not in node_ratio or ratio < node_ratio[rule_key]:
            node_ratio[rule_key] = ratio
            info["border"] = color
        graph.rules.add(step.action_id or rule_key)

        output_key = add_item(step.item, ratio, best)
        # 产出：rule -> item。根节点直接产出 target，这条边同时是「候选来源」，
        # 标签写整条路线的总成本；只有一个候选时没有比较，不必标红。
        is_candidate = root and output_key == graph.target
        add_edge(
            rule_key,
            output_key,
            f"yield:{step.action_id}",
            f"{total:.1f} TU" if is_candidate else "获得",
            _tooltip(step),
            ratio,
            color,
        )

        for child in step.children:
            child_key = _item_key(child.item)
            if child.note.startswith("环"):
                # 环不再画：连边带节点一起省掉，避免图上绕回 target。
                # 这条前置已经在这条路径的上游出现过，凭空多一条回边只会打结。
                continue
            emit(child, ratio, best=best)
            add_edge(
                child_key,
                rule_key,
                f"need:{child.action_id or child.item}",
                "获得" if child.need == 1.0 else _fmt_need(child.need),
                _tooltip(child),
                ratio,
                color,
            )

    for tree in trees:
        ratio = tree.total_cost / best if best > 0 else 1.0
        emit(
            tree.root,
            ratio,
            root=True,
            best=len(trees) > 1 and tree.rank == 1,
            total=tree.total_cost,
        )

    # 剪掉环之后可能剩下没有边的节点（整条链都只是回边），一并清掉。
    connected = {source for source, _, _ in graph.edges} | {
        destination for _, destination, _ in graph.edges
    }
    for key in [key for key in graph.nodes if key != graph.target and key not in connected]:
        del graph.nodes[key]

    return graph
