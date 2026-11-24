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


def test_single_candidate_edges_use_the_cost_ramp() -> None:
    """单候选分叉不标红：只有多来源比较时红色才有意义。"""
    shared = _step("minecraft:pickaxe", "craft:pickaxe#0")
    trees = [
        _tree(1, 10.0, _step("minecraft:x", "mine:ore", children=(shared,))),
        _tree(2, 40.0, _step("minecraft:x", "loot:chest", children=(shared,))),
    ]
    dot = route_graph.build_dot(trees, "minecraft:x")
    assert (
        f'"craft:pickaxe#0" -> "mine:ore"'
        f' [color="{route_graph.BEST_COLOR}"' in dot
    )
    assert (
        f'"craft:pickaxe#0" -> "loot:chest"'
        f' [color="{route_graph.WORST_COLOR}"' in dot
    )


def test_only_branched_decisions_highlight_the_best() -> None:
    """target 有两条候选来源时，只有成本最低的那条标红。"""
    trees = [
        _tree(1, 10.0, _step("minecraft:x", "mine:ore")),
        _tree(2, 20.0, _step("minecraft:x", "loot:chest")),
    ]
    dot = route_graph.build_dot(trees, "minecraft:x")
    assert (
        f'"mine:ore" -> "target" [color="{route_graph.HIGHLIGHT_COLOR}"' in dot
    )
    assert (
        f'"loot:chest" -> "target" [color="{route_graph.WORST_COLOR}"' in dot
    )
    assert f'"loot:chest" -> "target" [color="{route_graph.HIGHLIGHT_COLOR}"' not in dot


def test_action_preconditions_are_not_highlighted() -> None:
    """一个动作有多个前置（AND）时，不能把其中一条当「最佳候选」标红。"""
    root = _step(
        "minecraft:x",
        "loot:end_cities",
        children=(
            _step("minecraft:a", "travel:a"),
            _step("minecraft:b", "travel:b"),
        ),
    )
    dot = route_graph.build_dot([_tree(1, 10.0, root)], "minecraft:x")
    assert route_graph.HIGHLIGHT_COLOR not in dot
    assert (
        dot.count(f'-> "loot:end_cities" [color="{route_graph.BEST_COLOR}"') == 2
    )


def test_best_route_gets_a_red_highlight() -> None:
    """路线对照表里的最佳行仍用红色色块。"""
    assert route_graph.route_ink(1.0) == route_graph.HIGHLIGHT_COLOR
    assert route_graph.route_ink(1.01) != route_graph.HIGHLIGHT_COLOR
    assert route_graph.route_ink(route_graph.COST_RATIO_CAP) == route_graph.WORST_COLOR


def test_worst_branch_gets_the_lightest_color() -> None:
    """最浅色固定给本图最差分支，而不是固定的 4 倍端点。"""
    shared = _step("minecraft:pickaxe", "craft:pickaxe#0")
    trees = [
        _tree(1, 10.0, _step("minecraft:x", "mine:ore", children=(shared,))),
        _tree(2, 13.0, _step("minecraft:x", "loot:chest", children=(shared,))),
    ]
    dot = route_graph.build_dot(trees, "minecraft:x")
    assert (
        f'"craft:pickaxe#0" -> "loot:chest"'
        f' [color="{route_graph.WORST_COLOR}"' in dot
    )


def test_notes_and_quotes_are_escaped() -> None:
    """截断/环节点用虚线；HTML label 里的引号不会破坏 DOT 语法。"""
    step = _step("minecraft:x", 'weird:"name"', note="递归深度用尽")
    dot = route_graph.build_dot([_tree(1, 1.0, step)], "minecraft:x")
    assert 'style="dashed,filled"' in dot
    assert "label=<<TABLE" in dot
    assert "递归深度用尽" in dot
    assert "weird:" in dot

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
