"""前置脆弱点：换掉某个前置的当前来源后，整条路线贵多少。"""

from __future__ import annotations

import pytest

from bingo_grading.plan import MODE_PER_USE, Action, ActionSet, Requirement, solve
from bingo_grading.plan.explain import rank_paths
from bingo_grading.plan.frontiers import frontiers


def test_switching_the_only_frontier_raises_the_route_cost() -> None:
    actionset = ActionSet(
        "frontier",
        (
            Action(
                "make",
                "minecraft:t",
                1.0,
                {"minecraft:t": 1.0},
                requires=(Requirement("minecraft:p", 1.0, MODE_PER_USE),),
            ),
            Action("p1", "minecraft:p", 1.0, {"minecraft:p": 1.0}),
            Action("p2", "minecraft:p", 4.0, {"minecraft:p": 1.0}),
        ),
    )
    solved = solve(actionset, "minecraft:t", 1.0, prune_dominated=False)
    tree = rank_paths(actionset, solved, "minecraft:t", limit=1)[0]
    rows = frontiers(actionset, solved, tree, prune_dominated=False)
    assert [row.item for row in rows] == ["minecraft:p"]
    assert rows[0].action == "p1"
    assert rows[0].alternative == "p2"
    assert rows[0].delta == pytest.approx(3.0)
    assert rows[0].delta_ratio == pytest.approx(1.5)


def test_route_without_alternatives_has_no_frontiers() -> None:
    actionset = ActionSet(
        "plain",
        (Action("make", "minecraft:t", 1.0, {"minecraft:t": 1.0}),),
    )
    solved = solve(actionset, "minecraft:t", 1.0, prune_dominated=False)
    tree = rank_paths(actionset, solved, "minecraft:t", limit=1)[0]
    assert frontiers(actionset, solved, tree, prune_dominated=False) == []
