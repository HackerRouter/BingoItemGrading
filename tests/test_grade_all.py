"""`bg grade --all` 的联合计算：一次建图覆盖多个目标。"""

from __future__ import annotations

import pytest

from bingo_grading.case.context import CaseContext
from bingo_grading.sources import actions

pytestmark = pytest.mark.skipif(
    not pytest.importorskip("bingo_grading.paths").STATS_ROOT.joinpath("26.3", "spatial.jsonl").exists(),
    reason="需要统计快照",
)


@pytest.fixture(scope="module")
def ctx() -> CaseContext:
    from bingo_grading import paths

    return CaseContext.load(paths.STATS_ROOT / "26.3")


def test_joint_build_covers_every_single_target(ctx: CaseContext) -> None:
    """联合构建的图是各单件图的超集。

    全库计算靠这一点省时间：`visit` 的 `done` 集合让共享前置只展开一次，
    所以联合图里必须有每件单独构建时会生成的全部动作。少了任何一个，
    该物品在全库口径下就会失去一条来源。
    """
    items = ["minecraft:coal", "minecraft:iron_ingot", "minecraft:torch"]
    joint = actions.build(ctx, items[0], extra_targets=items[1:])
    joint_ids = {action.action_id for action in joint.actionset().actions}
    for name in items:
        single = actions.build(ctx, name)
        missing = [
            action.action_id
            for action in single.actionset().actions
            if action.action_id not in joint_ids
        ]
        assert not missing, f"{name} 的动作在联合图里缺失：{missing[:5]}"


def test_joint_build_reports_progress(ctx: CaseContext) -> None:
    """进度回调按目标逐个触发，且总数与实际展开的目标数一致。"""
    items = ["minecraft:coal", "minecraft:iron_ingot", "minecraft:torch"]
    seen: list[tuple[int, int, str]] = []
    actions.build(
        ctx,
        items[0],
        extra_targets=items[1:],
        progress=lambda index, total, name: seen.append((index, total, name)),
    )
    assert [entry[0] for entry in seen] == [1, 2, 3]
    assert {entry[1] for entry in seen} == {3}
    assert [entry[2] for entry in seen] == items


def test_two_builds_are_identical(ctx: CaseContext) -> None:
    """同一份数据连建两次，动作序列必须逐位相同。

    这是 §2.1 的回归防线：`axolotl_bucket` / `sulfur_cube_bucket` 这类
    「只有一条来源 + 一个 `per_use` 前置」的物品曾出现过空分在 1 与 3 之间跳、
    同一次运行里 JSON 有分而 CSV 没分。怀疑是构建时集合迭代顺序不同，
    导致动作顺序变化、预算边界上翻转。

    两次构建之间要清掉构建期的 `lru_cache`，否则测的是缓存命中而不是构建。
    `ctx` 自带的缓存（`pack_version` / `mining` / 动作表）是有意的，
    它们只存读盘结果，不影响展开口径。
    """
    from bingo_grading.sources.actions import common as action_common
    from bingo_grading.sources.actions import transmute

    items = ["minecraft:axolotl_bucket", "minecraft:coal", "minecraft:torch"]

    def build_once():
        transmute._transmute_rules.cache_clear()
        action_common._structure_maps.cache_clear()
        return actions.build(ctx, items[0], extra_targets=items[1:]).actionset()

    first = build_once()
    second = build_once()
    assert [action.action_id for action in first.actions] == [
        action.action_id for action in second.actions
    ]
    assert [action.as_dict(full=True) for action in first.actions] == [
        action.as_dict(full=True) for action in second.actions
    ]
