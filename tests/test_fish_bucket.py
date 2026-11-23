"""鱼桶路线：用桶舀 vs 跟渔夫买，以及栖息地差异。"""

from __future__ import annotations

from pathlib import Path

import pytest
from bingo_grading import grade
from bingo_grading.case.context import CaseContext
from bingo_grading.plan import solve
from bingo_grading.sources import actions

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "stats" / "26.3"
INDEX = ROOT / "build" / "26.3" / "source_index.jsonl"

needs_data = pytest.mark.skipif(
    not SNAPSHOT.exists() or not INDEX.exists(),
    reason=f"缺少快照 {SNAPSHOT} 或来源索引 {INDEX}",
)


@pytest.fixture(scope="module")
def ctx() -> CaseContext:
    return CaseContext.load(SNAPSHOT)


@needs_data
def test_scoop_source_is_reachable(ctx: CaseContext) -> None:
    """`code/mob_buckets` 是代码推导的来源，没有掉落期望，必须单独建模。"""
    built = actions.build(ctx, "minecraft:cod_bucket")
    scoops = [
        action
        for action in built.bundle.actions
        if action.action_id.startswith("scoop:") and action.item == "minecraft:cod_bucket"
    ]
    assert len(scoops) == 1, [a.action_id for a in built.bundle.actions if "cod_bucket" in a.item]
    action = scoops[0]
    # 空桶被消耗成鱼桶，所以是 per_use 而不是 once。
    modes = {req.item: req.mode for req in action.requires}
    assert modes.get("minecraft:bucket") == "per_use", modes


@needs_data
def test_scoop_beats_trading_for_cod(ctx: CaseContext) -> None:
    """河里捞一条鳕鱼比跑去村庄找渔夫便宜。"""
    built = actions.build(ctx, "minecraft:cod_bucket")
    aset = built.actionset()
    solved = solve(aset, "minecraft:cod_bucket", 1.0)
    cost, action_id, _, _ = grade.best_whole_cost(
        aset, solved.curves, "minecraft:cod_bucket", 1.0
    )
    assert cost is not None
    # 两条来源并列：`scoop:`（直接走去河里舀）与 `scoop_spawn:`（去群系等它刷再舀）。
    # 谁便宜由数据决定，测试只要保证走的确实是「用桶舀」这一类，不是交易。
    assert action_id.startswith(("scoop:", "scoop_spawn:")), f"应当是舀来的，实际走 {action_id}"


@needs_data
def test_habitat_changes_the_distance(ctx: CaseContext) -> None:
    """鲑鱼能在河里捞，河豚只能在暖/温海洋——距离必须不同。"""
    river, river_biome = ctx.water_search_cost(
        ("cold_ocean", "frozen_ocean", "frozen_river", "river")
    )
    warm, warm_biome = ctx.water_search_cost(
        ("deep_lukewarm_ocean", "lukewarm_ocean", "warm_ocean")
    )
    assert "river" in river_biome
    assert river.value < warm.value, (river.detail, warm.detail)
    assert "warm" in warm_biome or "lukewarm" in warm_biome


@needs_data
def test_cave_water_is_reported_not_guessed(ctx: CaseContext) -> None:
    """美西鰭住在洞穴水体里，地表占比法算不出「怎么下去」，不能硬给个数。

    但「算不出地表距离」不等于「没路线」：美西鰭是**周期刷怪**（`lush_caves`
    在 `mob_spawn` 里有权重），所以会走「去那个群系等它刷再舀」，
    而不是拿地表水面的距离蒙一个数。
    """
    assert ctx.water_search_cost(("lush_caves",)) is None
    built = actions.build(ctx, "minecraft:axolotl_bucket")
    ids = [
        action.action_id
        for action in built.bundle.actions
        if action.item == "minecraft:axolotl_bucket"
    ]
    assert ids, "应当有「去繁茂洞穴等刷」这条来源"
    assert all(i.startswith("scoop_spawn:") for i in ids), ids
