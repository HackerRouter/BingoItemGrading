"""路线合成图：成本比着色、跨路线共享节点、DOT/HTML 落盘。"""

from __future__ import annotations

import pytest

from bingo_grading import route_graph
from bingo_grading.plan.explain import PathTree, Step


def _step(
    item: str,
    action_id: str,
    *,
    cost: float = 1.0,
    need: float = 1.0,
    children: tuple[Step, ...] = (),
    note: str = "",
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


def test_route_color_goes_from_deep_to_light() -> None:
    """最优 = 最深色；成本比到上限时到最浅色，中间单调变浅。"""
    assert route_graph.route_color(1.0) == route_graph.BEST_COLOR
    assert route_graph.route_color(route_graph.COST_RATIO_CAP) == route_graph.WORST_COLOR
    middle = route_graph.route_color(2.0)
    assert middle not in (route_graph.BEST_COLOR, route_graph.WORST_COLOR)
    assert route_graph.route_color(1.0) != middle != route_graph.route_color(3.0)


def test_nodes_are_shared_across_routes() -> None:
    """同一动作出现在两条路线里时只画一个节点。"""
    shared = _step("minecraft:pickaxe", "craft:pickaxe#0")
    trees = [
        _tree(1, 10.0, _step("minecraft:x", "mine:ore", children=(shared,))),
        _tree(2, 20.0, _step("minecraft:x", "loot:chest", children=(shared,))),
    ]
    dot = route_graph.build_dot(trees, "minecraft:x")
    assert dot.count('"craft:pickaxe#0" [') == 1
    # 两条路线各有一条边（指向不同的父动作），节点本身共用
    assert dot.count('"craft:pickaxe#0" ->') == 2


def test_edges_take_the_most_prioritized_color() -> None:
    """共享边按最优先的那条路线着色，不会被后面的浅色覆盖。"""
    shared = _step("minecraft:pickaxe", "craft:pickaxe#0")
    trees = [
        _tree(1, 10.0, _step("minecraft:x", "mine:ore", children=(shared,))),
        _tree(2, 40.0, _step("minecraft:x", "loot:chest", children=(shared,))),
    ]
    dot = route_graph.build_dot(trees, "minecraft:x")
    best = route_graph.BEST_COLOR
    worst = route_graph.WORST_COLOR
    assert (
        f'"craft:pickaxe#0" -> "mine:ore"'
        f' [color="{best}"' in dot
    )
    assert (
        f'"craft:pickaxe#0" -> "loot:chest"'
        f' [color="{worst}"' in dot
    )
    assert worst in dot, "第二条路线的边仍是浅色"


def test_notes_and_quotes_are_escaped() -> None:
    """截断/环节点用虚线，标签里的引号不会破坏 DOT 语法。"""
    step = _step("minecraft:x", 'weird:"name"', note="递归深度用尽")
    dot = route_graph.build_dot([_tree(1, 1.0, step)], "minecraft:x")
    assert 'style="dashed,filled"' in dot
    assert '\\"' in dot


def test_write_outputs_always_writes_dot_and_html(tmp_path) -> None:
    trees = [_tree(1, 1.0, _step("minecraft:x", "mine:ore"))]
    written = route_graph.write_outputs(tmp_path / "graph", trees, "minecraft:x")
    names = {path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for path in written}
    assert "graph.dot" in names
    assert "graph.html" in names
    assert (tmp_path / "graph.dot").read_text(encoding="utf-8").startswith("digraph")
    if route_graph.graphviz_available():
        assert "graph.svg" in names
        assert "<svg" in (tmp_path / "graph.html").read_text(encoding="utf-8")
    else:
        assert "Graphviz" in (tmp_path / "graph.html").read_text(encoding="utf-8")


@pytest.mark.skipif(
    not route_graph.graphviz_available(), reason="没有 Graphviz（dot）"
)
def test_dot_is_accepted_by_graphviz(tmp_path) -> None:
    """生成的 DOT 必须是合法语法；非法时 dot 会返回非零。"""
    trees = [_tree(1, 1.0, _step("minecraft:x", "mine:ore"))]
    dot = route_graph.build_dot(trees, "minecraft:x")
    result = route_graph._dot_to_svg(dot)
    assert result is not None and "<svg" in result
