"""路径树：把曲线的第 k 优段摊成一条可读的链。"""

from __future__ import annotations

from pathlib import Path

import pytest

from bingo_grading.case.context import CaseContext
from bingo_grading.case.sources import ActionBundle
from bingo_grading.case.tools import ensure_tool
from bingo_grading.plan import (
    MODE_ONCE,
    MODE_PER_USE,
    Action,
    ActionSet,
    Requirement,
    solve,
)
from bingo_grading.plan.explain import rank_paths, render

SNAPSHOT = Path(__file__).resolve().parents[1] / "data" / "stats" / "26.3"

pytestmark = pytest.mark.skipif(
    not SNAPSHOT.exists(), reason=f"缺少统计快照 {SNAPSHOT}"
)


@pytest.fixture(scope="module")
def solved_bundle():
    """工具链里的木板：`oak_log` 直达与 `oak_wood` 折算两条路线都在。"""
    bundle = ActionBundle(label="toolchain")
    assert ensure_tool(bundle, CaseContext.load(SNAPSHOT), "minecraft:iron_pickaxe")
    actionset = bundle.actionset()
    return actionset, solve(actionset, "minecraft:oak_planks", 1.0)


def test_paths_are_ranked_by_price(solved_bundle) -> None:
    actionset, solved = solved_bundle
    trees = rank_paths(actionset, solved, "minecraft:oak_planks", limit=3)
    assert [tree.rank for tree in trees] == [1, 2, 3]
    costs = [tree.unit_cost for tree in trees]
    assert costs == sorted(costs)
    assert trees[0].rank_gap == 0.0
    assert trees[1].rank_gap > 0


def test_same_price_sources_share_a_rank() -> None:
    """两条来源同价时名次并列（1、1、3）；近价仍按位置排名。"""
    actionset = ActionSet(
        "tie",
        (
            Action("a", "minecraft:x", 2.0, {"minecraft:x": 1.0}),
            Action("b", "minecraft:x", 2.0, {"minecraft:x": 1.0}),
            Action("c", "minecraft:x", 3.0, {"minecraft:x": 1.0}),
        ),
    )
    solved = solve(actionset, "minecraft:x", 1.0, prune_dominated=False)
    trees = rank_paths(actionset, solved, "minecraft:x", limit=3)
    assert [tree.rank for tree in trees] == [1, 1, 3]
    assert [tree.rank_gap for tree in trees] == [0.0, 0.0, 1.0]


def test_second_best_shows_the_extra_step(solved_bundle) -> None:
    """木板上游换成 `oak_wood` 时，链里要能看见「4 原木 → 3 木」的额外一步。"""
    actionset, solved = solved_bundle
    trees = rank_paths(actionset, solved, "minecraft:oak_planks", limit=6)
    tree = next(
        tree
        for tree in trees
        if any(child.item == "minecraft:oak_wood" for child in tree.root.children)
    )
    wood = next(
        child for child in tree.root.children if child.item == "minecraft:oak_wood"
    )
    log = next(
        child for child in wood.children if child.item == "minecraft:oak_log"
    )
    # 1 块木板 = 0.25 个木板配方批次；一块 oak_wood 出 3 块木板 → 4 原木 / 3 木
    assert log.need == pytest.approx(4 / 3 * 0.25)


def test_once_prerequisites_are_counted_once() -> None:
    """同一个 `once` 前置在一条链上只该付一次，重复出现要标已计。

    用合成图构造：木头与木板各要一次「村庄」，`once` 只该收一次 5 TU。
    """
    actionset = ActionSet(
        "once",
        (
            Action("village", "capability:village", 5.0, {"capability:village": 1.0}),
            Action(
                "log",
                "minecraft:oak_log",
                1.0,
                {"minecraft:oak_log": 1.0},
                requires=(Requirement("capability:village", 1.0, MODE_ONCE),),
            ),
            Action(
                "planks",
                "minecraft:oak_planks",
                1.0,
                {"minecraft:oak_planks": 1.0},
                requires=(
                    Requirement("capability:village", 1.0, MODE_ONCE),
                    Requirement("minecraft:oak_log", 1.0, MODE_PER_USE),
                ),
            ),
        ),
    )
    solved = solve(actionset, "minecraft:oak_planks", 1.0)
    trees = rank_paths(actionset, solved, "minecraft:oak_planks", limit=1)
    rows = [line for line in render(trees).splitlines() if "capability:village" in line]
    assert len(rows) > 1  # 链上重复出现
    # 只有一处真的付了钱
    paid = [row for row in rows if "本步 5.0000" in row]
    assert len(paid) == 1
    # 到岸价 = 木板 1 + 原木 1 + 村庄 5；村庄只算一次
    assert trees[0].total_cost == pytest.approx(7.0)


def test_paths_render_mentions_every_step(solved_bundle) -> None:
    actionset, solved = solved_bundle
    text = render(rank_paths(actionset, solved, "minecraft:oak_planks", limit=2))
    assert "minecraft:oak_log" in text
    assert "minecraft:oak_wood" in text
