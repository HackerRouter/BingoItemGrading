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


def _cost_tree(
    step: Step, cache: dict[int, tuple[float, dict[str, float], float]]
) -> tuple[float, dict[str, float], float]:
    """`(节点整次价, 名字→金额, 本节点固定合计)`。

    **不递归**：`unit_cost` 已含直接前置的边际（`per_invocation_cost` 折进去了），
    `fixed` 已含全部上游能力的一次性开销（`fixed_cost_of` 按名字去重后透传）。
    所以一个节点的整次价就是 `单价 × 需要量 + 固定`，子节点是它的明细而不是加项。
    递归相加会把前置算两遍。
    """
    key = id(step)
    if key in cache:
        return cache[key]
    names = dict(step.fixed)
    fixed_total = sum(amount for amount in names.values())
    total = step.need * step.unit_cost + fixed_total
    cache[key] = (total, names, fixed_total)
    return cache[key]


def _price_lines(
    step: Step, cache: dict[int, tuple[float, dict[str, float], float]]
) -> list[str]:
    """`单价 × 需要量 [+ 固定] = 整次` 一行写完，等式自洽。

    `整次` 是项目既有口径（`whole_cost_tu`）：凑够 `need` 件的总价，含一次性开销。
    它**不是**「子节点相加」：`单价` 已含直接前置的边际、`固定` 已含全部上游
    一次性开销，子节点是它的明细而不是加项。
    """
    if not step.unit_cost or not math.isfinite(step.unit_cost):
        return []
    total, names, _ = _cost_tree(step, cache)
    line = f"{step.unit_cost:.2f} TU {_fmt_need(step.need)}"
    fixed_total = sum(names.values())
    if fixed_total:
        line += f" + {fixed_total:.2f} 固定"
    if step.children and abs(total - step.subtotal) > 1e-9:
        line += f" = {total:.2f} 整次"
    return [line]


def _node_label(
    step: Step, cache: dict[int, tuple[float, dict[str, float], float]]
) -> str:
    """动作节点：名称 / 描述 / `单价 TU × 需要量 [+ 固定]` / `合计`。"""
    title = step.action_id.replace("minecraft:", "") if step.action_id else short(step.item)
    lines = [title]
    if step.label:
        head = step.label.split("（", 1)[0].strip().replace("minecraft:", "")
        if head:
            lines.append(head[:48] + ("…" if len(head) > 48 else ""))
    lines.extend(_price_lines(step, cache))
    if step.note:
        lines.append(_note(step))
    rows = "".join(f"<TR><TD>{_html_text(line)}</TD></TR>" for line in lines)
    return (
        '<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="3">'
        + rows
        + "</TABLE>"
    )


def _per_unit(need: float, parent_need: float) -> float:
    """前置总量折算成「每件产物消耗几个」。父需求为 0 时不折算。"""
    if not parent_need:
        return need
    return need / parent_need


def _tooltip(
    step: Step, cache: dict[int, tuple[float, dict[str, float], float]]
) -> str:
    """只写图上看不到的东西：单价的分解、固定成本怎么合并的、调用次数、来源全名。

    节点标签上已有的（动作名、描述、`单价 × 需要量 + 固定 = 整次`、备注）不再重复。
    """
    _total, names, own_fixed = _cost_tree(step, cache)
    pieces: list[str] = []
    per_use = [child for child in step.children if not child.once]
    once = [child for child in step.children if child.once]
    if per_use:
        parts = [f"本动作 {step.own_unit_cost:.2f}"]
        parts.extend(
            f"{short(child.item)} {child.unit_cost:.2f}×{_per_unit(child.need, step.need):g}"
            for child in per_use
        )
        pieces.append("单价 = " + " + ".join(parts))
    if names:
        detail = " + ".join(
            f"{name.rsplit(':', 1)[-1]} {amount:.2f}"
            for name, amount in sorted(names.items())
        )
        line = f"固定 = {detail}"
        children_fixed = sum(_cost_tree(child, cache)[2] for child in step.children)
        if children_fixed > own_fixed + 1e-9:
            line += f"（前置合计 {children_fixed:.2f}，同名只算一次）"
        pieces.append(line)
    if once:
        pieces.append("一次性前置：" + "、".join(short(child.item) for child in once))
    if abs(step.calls - step.need) > 1e-9:
        pieces.append(f"调用 {step.calls:g} 次")
    if step.source:
        pieces.append(step.source)
    if step.label and len(step.label) > 48:
        # 图上把 label 截到 48 字，全文只有这里能看到。
        pieces.append(step.label)
    return "\n".join(pieces)


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
    # 成本按 Step 对象缓存：同一棵树里的节点各出现一次，跨路线共享时才复用。
    cost_cache: dict[int, tuple[float, dict[str, float], float]] = {}

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
                "label": _node_label(step, cost_cache),
                "html": True,
                "sort": "rule",
                "tooltip": _tooltip(step, cost_cache),
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
            _tooltip(step, cost_cache),
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
                _tooltip(child, cost_cache),
                ratio,
                color,
            )

    # 并列最优只锚定第一条：多条红链会把整张图染满。
    anchor = min(range(len(trees)), key=lambda index: trees[index].rank, default=-1)
    for index, tree in enumerate(trees):
        ratio = tree.total_cost / best if best > 0 else 1.0
        emit(
            tree.root,
            ratio,
            root=True,
            best=len(trees) > 1 and index == anchor,
            total=tree.total_cost,
        )

    # 剪掉环之后可能剩下没有边的节点（整条链都只是回边），一并清掉。
    connected = {source for source, _, _ in graph.edges} | {
        destination for _, destination, _ in graph.edges
    }
    for key in [key for key in graph.nodes if key != graph.target and key not in connected]:
        del graph.nodes[key]

    return graph
