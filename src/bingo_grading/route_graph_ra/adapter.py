"""本项目的路线树 → RA 风格 `PathGraph`（item / rule 二分）。

图的形状与 RA 一致：

- **item 节点**（矩形）：一个物品。多条入边 = 同一物品的多个候选来源（OR）；
- **rule 节点**（菱形）：一条动作。多条入边 = 该动作的并列前置（AND）；
- 边一律「来源 → 产物」：`item(前置) -> rule -> item(产物)`。

`rank_paths` 给出的树只展开**根级**候选（每个前置取自己的最优来源）。要看上游的
候选，传 `solved` + `actionset` + `branches`：`to_path_graph` 会按广度遍历整张图，
给每个「有多个来源」的物品补上候选规则节点。候选数受 `branches` 限制（0 = 全部），
节点总数受 `max_nodes` 兜底，被截掉的数量记进 `graph.omitted` 并画成显式节点。
"""

from __future__ import annotations

import html
import math
import re
from collections import deque

from ..plan.explain import MAX_DEPTH, PathTree, Step, _step as build_step, has_cycle
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


_RECIPE_TAIL = re.compile(r"（[^（）]*json[^（）]*）")

# 候选没画出来的两种原因：依赖回到自己、代价太高。
SKIP_CYCLIC = "依赖自己"
SKIP_COSTLY = "贵过阈值或超出上限"


def _clean_label(text: str) -> str:
    """去掉 label 里对读路线没用的部分：`（crafting_shapeless；data/…json）` 与命名空间前缀。"""
    text = _RECIPE_TAIL.sub("", text).replace("minecraft:", "")
    return text.strip()


def _trim(text: str, limit: int) -> str:
    """超长文本截断并交代原长，避免 tooltip 被一条长描述占满。"""
    return text if len(text) <= limit else f"{text[:limit]}…（共 {len(text)} 字）"


def _bare(name: str) -> str:
    """`capability:nether_access` / `minecraft:coal` → 最后一段，用于跨形式判重。"""
    return name.rsplit(":", 1)[-1]


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
            f"{_bare(name)} {amount:.2f}" for name, amount in sorted(names.items())
        )
        line = f"固定 = {detail}"
        children_fixed = sum(_cost_tree(child, cache)[2] for child in step.children)
        if children_fixed > own_fixed + 1e-9:
            line += f"（前置合计 {children_fixed:.2f}，同名只算一次）"
        pieces.append(line)
    if once:
        # 固定行已经逐笔列出金额的前置不再重复，这行只补「金额为 0」的共享前置。
        paid = {_bare(name) for name in names}
        extra = [short(child.item) for child in once if _bare(child.item) not in paid]
        if extra:
            pieces.append("一次性前置：" + "、".join(extra))
    if abs(step.calls - step.need) > 1e-9:
        pieces.append(f"调用 {step.calls:g} 次")
    # 来源与完整描述合并成一行：两者都是「这条动作出自哪里」。
    tail: list[str] = []
    if step.source:
        tail.append(step.source.replace("minecraft:", ""))
    if step.label and len(step.label) > 48:
        # 图上把 label 截到 48 字；这里给全文（去掉配方文件路径与命名空间）。
        tail.append(_trim(_clean_label(step.label), 100))

    if tail:
        pieces.append(" ｜ ".join(tail))
    return "\n".join(pieces)


def to_path_graph(
    trees: list[PathTree],
    target: str,
    *,
    rankdir: str = "TB",
    solved=None,
    actionset=None,
    branches: int = 0,
    max_nodes: int = 0,
    depth: int = MAX_DEPTH,
    ratio_limit: float = 0.0,
) -> PathGraph:
    """把前 N 条路线转成一张 item / rule 图。

    `solved` / `actionset` 给出来时，额外展开上游候选：遍历整张图里出现的每个物品，
    按它的供给曲线补上「第二、第三……来源」的规则节点。候选数 `branches`（0 = 全部），
    节点上限 `max_nodes`（0 = 不限）。
    """
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
    ) -> bool:
        """画这条动作（连同它的下游）。返回是否画出了动作节点。"""
        if not step.action_id and step.note.startswith("once 前置"):
            # 「链上游已付过」只是记账占位，没有动作可画。
            # 画出来会多一个假节点和一条「获得」边；前置关系由调用方的
            # item → rule 边承担。物品节点仍要登记，否则那条边指向不存在的节点。
            add_item(step.item, ratio, best)
            return False
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
                # 回到本路线已经出现过的一步（`diamond` 拆钻石块，钻石块又要钻石合成）。
                # 画成不参与层级的虚线，读者才看得出这是「绕一圈」而不是凭空来的来源。
                add_item(child.item, ratio, best)
                add_edge(
                    child_key,
                    rule_key,
                    f"needcycle:{child.item}",
                    _fmt_need(child.need),
                    f"{child.item} 在本次路线里已经出现过，这一份按它的最优价计",
                    ratio,
                    color,
                    dashed=True,
                )
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
        return True

    # 并列最优只锚定第一条：多条红链会把整张图染满。
    anchor = min(range(len(trees)), key=lambda index: trees[index].rank, default=-1)
    for index, tree in enumerate(trees):
        ratio = tree.total_cost / best if best > 0 else 1.0
        emit(
            tree.root,
            ratio,
            root=True,
            # 单候选也标红：红色表示「这条路」，唯一时它就是那条路。
            # 不然图是蓝的、对照表 #1 是红的，两处对同一件事给了两个答案。
            best=index == anchor,
            total=tree.total_cost,
        )

    # 上游候选：给每个「有多个来源」的物品补上第二、第三…条规则。
    # `branches == 1` 表示每个物品只留最优那一条（等价于旧行为）。
    if solved is not None and actionset is not None and branches != 1:
        skipped = _expand_upstream(
            graph,
            solved,
            actionset,
            trees,
            branches=branches,
            max_nodes=max_nodes,
            depth=depth,
            emit=emit,
            ratio_limit=ratio_limit,
        )
        for index, (item, hidden) in enumerate(skipped.items()):
            key = f"omitted::{item}#{index}"
            count = len(hidden)
            listed = "\n".join(
                f"{number}. {_trim(action_id, 44)}"
                f"（{'依赖自己，不计入' if why == SKIP_CYCLIC else f'{ratio:.1f}×'}）"
                for number, (action_id, ratio, why) in enumerate(hidden[:6], start=1)
            )
            if count > 6:
                listed += f"\n…另 {count - 6} 条"
            reasons = []
            for spec in (SKIP_CYCLIC, SKIP_COSTLY):
                hit = sum(1 for _a, _r, why in hidden if why == spec)
                if hit:
                    reasons.append(spec if hit == count else f"{spec} {hit} 条")
            graph.nodes[key] = {
                "label": f"还有 {count} 条候选\n未画（见 tooltip）",
                "sort": "omitted",
                "tooltip": (
                    f"{item} 还有 {count} 条候选没画（"
                    + "，".join(reasons)
                    + "）。\n按代价从低到高：\n"
                    + listed
                ),
            }
            add_edge(
                key,
                _item_key(item),
                f"omitted:{index}",
                f"{count} 条",
                graph.nodes[key]["tooltip"],
                1.0,
                "#fb923c",
                dashed=True,
            )
        if skipped:
            graph.omitted = {item: len(hidden) for item, hidden in skipped.items()}

    # 剪掉环之后可能剩下没有边的节点（整条链都只是回边），一并清掉。
    connected = {source for source, _, _ in graph.edges} | {
        destination for _, destination, _ in graph.edges
    }
    for key in [key for key in graph.nodes if key != graph.target and key not in connected]:
        del graph.nodes[key]

    return graph


def _has_drawn_source(graph: PathGraph, item: str) -> bool:
    """这个物品在图里有没有实线来源（虚线只是「还有候选没画」的计数）。"""
    key = _item_key(item)
    return any(
        destination == key and tag not in graph.dashed
        for _source, destination, tag in graph.edges
    )


def _has_cycle(step: Step) -> bool:
    """这条候选的依赖里回到了自己（`diamond` → `diamond_block` → `diamond`）。

    这种候选的成本靠「自己给自己供货」算出来，画出来会剩一个没有入边的合成节点，
    看起来像上游真实存在的一步。整条不画，只留候选计数。
    """
    return has_cycle(step)


def self_serving(tree: PathTree) -> bool:
    """这条路线要靠自己供货（依赖成环），报价不成立：不可画，也不该拿来比价。"""
    return _has_cycle(tree.root)


def _expand_upstream(
    graph: PathGraph,
    solved,
    actionset,
    trees: list[PathTree],
    *,
    branches: int,
    max_nodes: int,
    depth: int,
    emit,
    ratio_limit: float = 0.0,
) -> dict[str, list[tuple[str, float, str]]]:
    """按广度遍历已有树里的每个物品，补上它自己的候选来源。

    节点跨路线共享（key 是 `action_id`），所以「补一次」等价于补到所有出现处；
    `expanded` 防止同一物品被反复展开。返回**每个物品没画出来的候选**
    `[(action_id, 相对最优的倍数, 原因), ...]`，供图上的「还有 N 条候选」节点列明细。

    `ratio_limit > 0` 时只画「贵不到这么多倍」的候选：差十倍的来源画上去只是噪音，
    还会把图撑到几千像素宽。依赖回到自己的候选一律不画（见 `_has_cycle`）。
    """
    queue: deque[tuple[str, float, float, frozenset[str]]] = deque()
    expanded: set[str] = set()
    skipped: dict[str, list[tuple[str, float, str]]] = {}
    cyclic = SKIP_CYCLIC
    costly = SKIP_COSTLY

    def enqueue(step: Step, ratio: float, stack: frozenset[str]) -> None:
        for child in step.children:
            if child.note.startswith("环"):
                continue
            queue.append((child.item, child.need, ratio, stack | {step.item}))
            enqueue(child, ratio, stack | {step.item})

    baseline = trees[0].total_cost if trees else 0.0
    for tree in trees:
        ratio = tree.total_cost / baseline if baseline > 0 else 1.0
        enqueue(tree.root, ratio, frozenset())

    while queue:
        item, need, ratio, stack = queue.popleft()
        if item in expanded or item in stack:
            continue
        expanded.add(item)
        curve = solved.curve_of(item)
        if len(curve.segments) < 2:
            continue
        head = curve.head
        best_local = (
            head.unit_cost * min(need, head.capacity) + head.fixed_cost if head else 0.0
        )
        candidates = curve.segments[1:]
        if branches > 0:
            candidates = candidates[: branches - 1]

        def local_ratio_of(segment) -> float:
            cost = segment.unit_cost * min(need, segment.capacity) + segment.fixed_cost
            return cost / best_local if best_local > 0 else 1.0

        # 最优那段的动作画不出来（原料全回到自己）时，这个物品在图上是悬空的：
        # 放宽阈值，至少留一条真实来源，贵也总比没有来源强。
        need_a_source = not _has_drawn_source(graph, item)

        for index, seg in enumerate(candidates):
            local_ratio = local_ratio_of(seg)
            if (ratio_limit and local_ratio > ratio_limit and not need_a_source) or (
                max_nodes and len(graph.nodes) >= max_nodes
            ):
                skipped.setdefault(item, []).extend(
                    (rest.action_id, local_ratio_of(rest), costly)
                    for rest in candidates[index:]
                )
                break
            step = build_step(
                actionset,
                solved,
                item,
                seg,
                need,
                depth=depth,
                stack=stack,
                seen_once=set(),
            )
            if _has_cycle(step):
                skipped.setdefault(item, []).append(
                    (seg.action_id, local_ratio, cyclic)
                )
                continue
            emit(step, local_ratio, best=False)
            need_a_source = False
            enqueue(step, local_ratio, stack)
    return skipped
