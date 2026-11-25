"""RA 风格路线图：item / rule 二分、红色锚点、环剪断、落盘。"""

from __future__ import annotations

from dataclasses import replace

import pytest

from bingo_grading import route_graph_ra
from bingo_grading.plan.explain import PathTree, Step
from bingo_grading.route_graph_ra.colors import (
    BEST_COLOR,
    HIGHLIGHT_COLOR,
    WORST_COLOR,
)


def _step(
    item: str,
    action_id: str,
    *,
    cost: float = 1.0,
    need: float = 1.0,
    children: tuple[Step, ...] = (),
    note: str = "",
    fixed: tuple[tuple[str, float], ...] = (),
    own_unit_cost: float = 0.0,
) -> Step:
    return Step(
        item=item,
        action_id=action_id,
        unit_cost=cost,
        need=need,
        calls=need,
        subtotal=cost * need,
        children=children,
        note=note,
        fixed=fixed,
        own_unit_cost=own_unit_cost,
    )


def _tree(rank: int, total: float, root: Step) -> PathTree:
    return PathTree(
        item="minecraft:x",
        rank=rank,
        unit_cost=root.unit_cost,
        rank_gap=total - 1.0,
        root=root,
        total_cost=total,
        need=1.0,
    )


def test_items_and_rules_are_separate_nodes() -> None:
    """物品是矩形节点、动作是菱形节点，边一律「来源 → 产物」。"""
    graph = route_graph_ra.to_path_graph(
        [_tree(1, 4.0, _step("minecraft:x", "smelt:x", children=(_step("minecraft:ore", "mine:ore"),)))],
        "minecraft:x",
    )
    assert graph.nodes["item::minecraft:x"]["sort"] == "item"
    assert graph.nodes["item::minecraft:ore"]["sort"] == "item"
    assert graph.nodes["rule::smelt:x"]["sort"] == "rule"
    assert graph.nodes["rule::smelt:x"]["html"] is True
    assert graph.target == "item::minecraft:x"
    assert ("rule::smelt:x", "item::minecraft:x", "yield:smelt:x") in graph.edges
    assert ("item::minecraft:ore", "rule::smelt:x", "need:mine:ore") in graph.edges
    assert ("rule::mine:ore", "item::minecraft:ore", "yield:mine:ore") in graph.edges


def test_rule_label_keeps_cost_and_quantity() -> None:
    """动作节点保留 `单价 TU × 需要量`，不写「单价:」占地方。"""
    graph = route_graph_ra.to_path_graph(
        [_tree(1, 4.0, _step("minecraft:x", "smelt:x", cost=2.12, need=3))],
        "minecraft:x",
    )
    label = graph.nodes["rule::smelt:x"]["label"]
    assert "2.12 TU ×3" in label
    assert "单价" not in label
    assert "CELLPADDING=\"3\"" in label


def test_rule_label_shows_fixed_cost() -> None:
    """固定成本必须上图，且与单价同一行：只写单价会让「单价低但固定贵」的来源看着更便宜。"""
    step = _step(
        "minecraft:x",
        "cast:x",
        cost=0.14,
        need=3.0,
        fixed=(("capability:lava_access", 48.4),),
    )
    graph = route_graph_ra.to_path_graph([_tree(1, 49.0, step)], "minecraft:x")
    node = graph.nodes["rule::cast:x"]
    assert "0.14 TU ×3 + 48.40 固定" in node["label"]
    assert "lava_access 48.4" in node["tooltip"]


def test_tooltip_explains_how_the_numbers_add_up() -> None:
    """悬停要能看出：单价里折进了哪些前置、固定成本合并掉了多少。"""
    blaze = _step(
        "minecraft:blaze_powder", "crush", cost=27.5, need=12.0,
        fixed=(("capability:nether", 155.27),),
    )
    pearl = _step(
        "minecraft:ender_pearl", "roam", cost=13.19, need=12.0,
        fixed=(("capability:nether", 74.01),),
    )
    root = _step(
        "minecraft:ender_eye",
        "craft",
        cost=45.69,
        need=12.0,
        children=(blaze, pearl),
        fixed=(("capability:nether", 155.27),),
        own_unit_cost=5.0,
    )
    graph = route_graph_ra.to_path_graph([_tree(1, 703.55, root)], "minecraft:x")
    tooltip = graph.nodes["rule::craft"]["tooltip"]
    # 45.69 = 5.00 自身 + 27.50×1 + 13.19×1（每个末影之眼各要 1 个烈焰粉、1 个珍珠）
    assert "单价 = 本动作 5.00 + blaze_powder 27.50×1 + ender_pearl 13.19×1" in tooltip
    # 前置固定 155.27 + 74.01 = 229.28，同名合并后 155.27
    assert "前置合计 229.28" in tooltip
    assert "同名只算一次" in tooltip
    # 图上已经写过的内容不再重复
    assert "本行" not in tooltip
    assert "整次（含全部前置）" not in tooltip


def test_once_child_is_not_folded_into_unit_price() -> None:
    """once 前置整笔进固定成本，不能出现在「单价构成」里（否则会算出负数）。"""
    state = _step("capability:state", "make_state", cost=341.9)
    root = _step(
        "minecraft:x",
        "use",
        cost=23.1,
        children=(state,),
        fixed=(("capability:state", 341.9),),
        own_unit_cost=23.1,
    )
    root = replace(root, children=(replace(state, once=True),))
    graph = route_graph_ra.to_path_graph([_tree(1, 365.0, root)], "minecraft:x")
    tooltip = graph.nodes["rule::use"]["tooltip"]
    assert "一次性前置：capability:state" in tooltip
    assert "本动作 -" not in tooltip


def test_label_shows_whole_cost() -> None:
    """等式自洽：`单价 × 需要量 + 固定 = 整次`，整次等于 `PathTree.total_cost`。"""
    child = _step(
        "minecraft:p",
        "p1",
        cost=10.0,
        fixed=(("capability:shared", 5.0),),
    )
    # 真实数据里父节点的 unit_cost 已含子节点的边际，这里同样构造：11 = 自身 1 + 子 10
    root = _step(
        "minecraft:x",
        "make",
        cost=11.0,
        need=2.0,
        children=(child,),
        fixed=(("capability:shared", 5.0),),
    )
    graph = route_graph_ra.to_path_graph([_tree(1, 27.0, root)], "minecraft:x")
    make = graph.nodes["rule::make"]
    assert "11.00 TU ×2 + 5.00 固定 = 27.00 整次" in make["label"]
    # 叶子节点自身就是全部（10 + 5），不另写「整次」
    assert "10.00 TU ×1 + 5.00 固定" in graph.nodes["rule::p1"]["label"]
    assert "整次" not in graph.nodes["rule::p1"]["label"]


def test_fractional_need_shows_as_reciprocal() -> None:
    """一次产出多件时，前置的 `×0.111` 写成 `×1/9`，图上才读得懂。"""
    root = _step(
        "minecraft:x",
        "craft:x",
        children=(_step("minecraft:block", "craft:block", need=1 / 9),),
    )
    graph = route_graph_ra.to_path_graph([_tree(1, 4.0, root)], "minecraft:x")
    assert graph.edges[("item::minecraft:block", "rule::craft:x", "need:craft:block")][0] == "×1/9"
    assert "×1/9" in graph.nodes["rule::craft:block"]["label"]


def test_depth_cut_note_says_cost_is_included() -> None:
    """深度截断的备注要说清「成本已计入」，而不是只写「未展开」。"""
    graph = route_graph_ra.to_path_graph(
        [_tree(1, 4.0, _step("minecraft:x", "mine:x", note="递归深度用尽，下游未展开"))],
        "minecraft:x",
    )
    label = graph.nodes["rule::mine:x"]["label"]
    assert "成本已计入" in label
    assert "未展开" not in label


def test_best_candidate_is_highlighted() -> None:
    """target 的多候选里只有最便宜的标红，其余走浓淡。"""
    trees = [
        _tree(1, 10.0, _step("minecraft:x", "mine:ore")),
        _tree(2, 20.0, _step("minecraft:x", "loot:chest")),
    ]
    graph = route_graph_ra.to_path_graph(trees, "minecraft:x")
    best = ("rule::mine:ore", "item::minecraft:x", "yield:mine:ore")
    other = ("rule::loot:chest", "item::minecraft:x", "yield:loot:chest")
    assert graph.edge_colors[best] == HIGHLIGHT_COLOR
    assert graph.edge_colors[other] == WORST_COLOR
    assert graph.edges[best][0] == "10.0 TU"


def test_only_one_highlight_among_many_candidates() -> None:
    trees = [
        _tree(1, 10.0, _step("minecraft:x", "a")),
        _tree(2, 10.5, _step("minecraft:x", "b")),
        _tree(3, 30.0, _step("minecraft:x", "c")),
    ]
    graph = route_graph_ra.to_path_graph(trees, "minecraft:x")
    reds = [key for key, color in graph.edge_colors.items() if color == HIGHLIGHT_COLOR]
    assert reds == [("rule::a", "item::minecraft:x", "yield:a")]


def test_action_preconditions_are_not_highlighted() -> None:
    """一个动作的多个前置是 AND，不能挑其中一条标红。"""
    root = _step(
        "minecraft:x",
        "loot:end_cities",
        children=(_step("minecraft:a", "travel:a"), _step("minecraft:b", "travel:b")),
    )
    graph = route_graph_ra.to_path_graph([_tree(1, 10.0, root)], "minecraft:x")
    assert HIGHLIGHT_COLOR not in graph.edge_colors.values()
    assert graph.edge_colors[("item::minecraft:a", "rule::loot:end_cities", "need:travel:a")] == BEST_COLOR


def test_cycle_child_is_dropped() -> None:
    """路径上已经出现过的前置直接不画：不回边、也不留孤立节点。"""
    root = _step(
        "minecraft:x",
        "craft:block",
        children=(
            _step(
                "minecraft:x",
                "loot:ore",
                note="环：这条路径上已经出现过，不再展开",
            ),
        ),
    )
    graph = route_graph_ra.to_path_graph([_tree(1, 10.0, root)], "minecraft:x")
    assert not [key for key in graph.edges if key[2] == "need:loot:ore"]
    assert not graph.dashed
    assert "rule::loot:ore" not in graph.nodes
    # target 自己没有出边，但必须留着
    assert "item::minecraft:x" in graph.nodes


def test_shared_action_is_one_node() -> None:
    """同一动作出现在两条路线里只画一个节点，边也不重复。"""
    shared = _step("minecraft:pickaxe", "craft:pickaxe#0")
    trees = [
        _tree(1, 10.0, _step("minecraft:x", "mine:ore", children=(shared,))),
        _tree(2, 20.0, _step("minecraft:x", "loot:chest", children=(shared,))),
    ]
    graph = route_graph_ra.to_path_graph(trees, "minecraft:x")
    assert sum(1 for key in graph.nodes if key == "rule::craft:pickaxe#0") == 1
    yield_edges = [
        key for key in graph.edges if key[0] == "rule::craft:pickaxe#0" and key[1] == "item::minecraft:pickaxe"
    ]
    assert len(yield_edges) == 1


def test_node_border_follows_the_cheapest_route() -> None:
    """共享节点取它出现过的最优先路线的颜色：最优路线上的节点是红边框。"""
    shared = _step("minecraft:pickaxe", "craft:pickaxe#0")
    trees = [
        _tree(1, 10.0, _step("minecraft:x", "mine:ore", children=(shared,))),
        _tree(2, 20.0, _step("minecraft:x", "loot:chest", children=(shared,))),
    ]
    graph = route_graph_ra.to_path_graph(trees, "minecraft:x")
    assert graph.nodes["item::minecraft:pickaxe"]["border"] == HIGHLIGHT_COLOR
    assert graph.nodes["rule::craft:pickaxe#0"]["border"] == HIGHLIGHT_COLOR


def test_whole_best_route_is_highlighted() -> None:
    """红色贯穿整条最优路线，而不只是连到 target 的那一条边。"""
    shared = _step("minecraft:pickaxe", "craft:pickaxe#0")
    trees = [
        _tree(1, 10.0, _step("minecraft:x", "mine:ore", children=(shared,))),
        _tree(2, 20.0, _step("minecraft:x", "loot:chest", children=(shared,))),
    ]
    graph = route_graph_ra.to_path_graph(trees, "minecraft:x")
    # 最优路线：pickaxe -> mine:ore -> x，两条边都红
    assert graph.edge_colors[("item::minecraft:pickaxe", "rule::mine:ore", "need:craft:pickaxe#0")] == HIGHLIGHT_COLOR
    assert graph.edge_colors[("rule::mine:ore", "item::minecraft:x", "yield:mine:ore")] == HIGHLIGHT_COLOR
    # 次优路线仍是浓淡
    assert graph.edge_colors[("item::minecraft:pickaxe", "rule::loot:chest", "need:craft:pickaxe#0")] != HIGHLIGHT_COLOR


def test_single_route_is_not_highlighted(tmp_path) -> None:
    """只有一条路线时没有比较，不标红。"""
    graph = route_graph_ra.to_path_graph(
        [_tree(1, 10.0, _step("minecraft:x", "mine:ore"))], "minecraft:x"
    )
    assert HIGHLIGHT_COLOR not in graph.edge_colors.values()


def test_same_price_routes_keep_one_red_marker(tmp_path) -> None:
    """同价的两条路线只让第一条带红色锚点，对照表名次并列。"""
    trees = [
        _tree(1, 10.0, _step("minecraft:x", "a")),
        _tree(1, 10.0, _step("minecraft:x", "b")),
    ]
    graph = route_graph_ra.to_path_graph(trees, "minecraft:x")
    assert graph.edge_colors[("rule::a", "item::minecraft:x", "yield:a")] == HIGHLIGHT_COLOR
    assert graph.edge_colors[("rule::b", "item::minecraft:x", "yield:b")] == BEST_COLOR
    html = route_graph_ra.render_html("<svg></svg>", trees, "minecraft:x")
    assert html.count(HIGHLIGHT_COLOR) == 1
    assert html.count("<td>#1</td>") == 2


def test_frontier_table_renders() -> None:
    """前置脆弱点表要写清替代来源与整条路线的差额。"""
    trees = [_tree(1, 10.0, _step("minecraft:x", "a"))]
    html = route_graph_ra.render_html(
        "<svg></svg>",
        trees,
        "minecraft:x",
        frontiers=[
            {
                "item": "minecraft:p",
                "action": "p1",
                "alternative": "p2",
                "route_total": 15.0,
                "delta": 3.0,
                "delta_ratio": 0.3,
            }
        ],
    )
    assert "前置替换成本" in html
    assert "p1" in html and "p2" in html
    assert "+3.00（+30.0%）" in html


def test_route_table_shows_three_decimals() -> None:
    """近价路线在两位小数下都显示 1.00×，对照表要给到千分位。"""
    trees = [
        _tree(1, 10.0, _step("minecraft:x", "a")),
        _tree(2, 10.028, _step("minecraft:x", "b")),
    ]
    html = route_graph_ra.render_html("<svg></svg>", trees, "minecraft:x")
    assert "1.000×" in html
    assert "1.003×" in html
    assert "1.00×" not in html


def test_root_edge_keeps_its_own_total() -> None:
    """同一动作在多棵树里作根时，边上的总成本不能串成别人的。"""
    trees = [
        _tree(1, 10.0, _step("minecraft:x", "a")),
        _tree(2, 12.0, _step("minecraft:x", "a", note="同动作的第二条路线")),
    ]
    graph = route_graph_ra.to_path_graph(trees, "minecraft:x")
    edge = ("rule::a", "item::minecraft:x", "yield:a")
    assert graph.edges[edge][0] == "10.0 TU"


def test_write_outputs_writes_dot_and_html(tmp_path) -> None:
    trees = [_tree(1, 10.0, _step("minecraft:x", "mine:ore"))]
    written = route_graph_ra.write_outputs(tmp_path / "graph", trees, "minecraft:x")
    names = {path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for path in written}
    assert "graph.dot" in names
    assert "graph.html" in names
    dot = (tmp_path / "graph.dot").read_text(encoding="utf-8")
    assert dot.startswith("digraph") and "label=<<" in dot
    html = (tmp_path / "graph.html").read_text(encoding="utf-8")
    assert "路线对照" in html
    if route_graph_ra.graphviz_available():
        assert "graph.svg" in names
        assert "<svg" in html
    else:
        assert "Graphviz" in html


def test_empty_trees_write_nothing(tmp_path) -> None:
    assert route_graph_ra.write_outputs(tmp_path / "graph", [], "minecraft:x") == []


@pytest.mark.skipif(not route_graph_ra.graphviz_available(), reason="没有 Graphviz（dot）")
def test_dot_is_accepted_by_graphviz() -> None:
    trees = [_tree(1, 10.0, _step("minecraft:x", "mine:ore", note="递归深度用尽"))]
    graph = route_graph_ra.to_path_graph(trees, "minecraft:x")
    svg = route_graph_ra.dot_to_svg(route_graph_ra.build_dot(graph, route_graph_ra.PathOptions()))
    assert svg is not None and "<svg" in svg
