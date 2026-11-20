"""两处「按层累加」的来源：袭击按波次、村民交易按等级。

两者都是**有顺序**的获取方式，不能把最终一层的产出摊到前面：
- 袭击想拿第 7 波的唤魔者，前 6 波必须打完；但只想拿第 5 波那 1 只时不必陪跑。
- 4 级交易要先升到 4 级，而升级本身要付出前面各级的一次交易对价。
"""

from __future__ import annotations

import math
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
def test_raid_emits_one_action_per_target_wave(ctx: CaseContext) -> None:
    """袭击按波次给出多个截断点，而不是只有「打完整场」一条。"""
    raids = ctx.raid_spawns("minecraft:evoker")
    assert raids, "唤魔者应当出现在袭击刷怪表里"
    _holder, _rule, per_wave_total, per_wave_target = raids[0]
    assert per_wave_total == sorted(per_wave_total), "波次必须按序号升序"
    assert [wave for wave, _ in per_wave_target], "目标生物应当有非零波次"

    built = actions.build(ctx, "minecraft:totem_of_undying")
    raid_actions = [
        action
        for action in built.bundle.actions
        if action.action_id.startswith("raid:") and action.item == "minecraft:totem_of_undying"
    ]
    # 每个「目标数量变化的波次」各一条，不是整场一条。
    assert len(raid_actions) == len(per_wave_target)
    costs = [action.cost for action in raid_actions]
    yields = [action.yields["minecraft:totem_of_undying"] for action in raid_actions]
    assert costs == sorted(costs), "越往后打越贵"
    assert yields == sorted(yields), "越往后打产出越多"


@needs_data
def test_raid_batches_are_not_pruned_as_dominated(ctx: CaseContext) -> None:
    """打完整场单价最低、但起步价最高，不能因此把中途收工的截断点剪掉。"""
    built = actions.build(ctx, "minecraft:totem_of_undying")
    aset = built.actionset()
    solved = solve(aset, "minecraft:totem_of_undying", 1.0)
    curve = solved.curves["minecraft:totem_of_undying"]
    raid_segments = [seg for seg in curve.segments if seg.action_id.startswith("raid:")]
    assert len(raid_segments) >= 2, "至少要有「中途收工」与「打完整场」两个候选"


@needs_data
def test_raid_whole_cost_does_not_shrink_by_sharing_one_event(ctx: CaseContext) -> None:
    """一次袭击出 4 个图腾，但拿 1 个不等于「整场 ÷ 4」——除非真的打完整场。"""
    built = actions.build(ctx, "minecraft:totem_of_undying")
    aset = built.actionset()
    solved = solve(aset, "minecraft:totem_of_undying", 1.0)
    one, action_id, _ = grade.best_whole_cost(
        aset, solved.curves, "minecraft:totem_of_undying", 1.0
    )
    assert one is not None
    action = next(a for a in aset.actions if a.action_id == action_id)
    calls = math.ceil(1.0 / action.effective_yield(action.item) - 1e-9)
    assert one >= action.cost * calls - 1e-6, (
        "整次成本至少要覆盖向上取整后的调用次数"
    )


@needs_data
def test_trade_levels_are_cumulative(ctx: CaseContext) -> None:
    """4 级交易挂一个「村民已到 4 级」的 once 前置，而不是把升级费并进单价。"""
    built = actions.build(ctx, "minecraft:ender_pearl")
    trades = [
        action
        for action in built.bundle.actions
        if action.action_id.startswith("trade:cleric/4")
        and action.item == "minecraft:ender_pearl"
    ]
    assert trades, "4 级牧师应当有末影珍珠报价"
    action = trades[0]
    once = {req.item for req in action.requires if req.mode == "once"}
    assert "capability:villager:cleric/4" in once, f"缺等级前置：{once}"
    # 购买对价只该是本级那 5 个绿宝石，不能再叠加升级费。
    per_use = {req.item: req.qty for req in action.requires if req.mode == "per_use"}
    assert per_use == {"minecraft:emerald": 5.0}, per_use


@needs_data
def test_training_trades_off_emerald_from_selling(ctx: CaseContext) -> None:
    """卖货换绿宝石的报价升级时只要原材料：卖来的绿宝石抵扣了开销。"""
    built = actions.build(ctx, "minecraft:ender_pearl")
    train = [
        action
        for action in built.bundle.actions
        if action.action_id.startswith("train:2:")
        and action.item == "capability:villager:cleric/2"
        and any(req.item == "minecraft:rotten_flesh" for req in action.requires)
    ]
    assert train, "卖腐肉换绿宝石那条升级动作应当存在"
    action = train[0]
    needs = {req.item for req in action.requires}
    assert "minecraft:rotten_flesh" in needs, f"卖腐肉换绿宝石那条才对：{needs}"
    assert "minecraft:emerald" not in needs, "卖来的绿宝石应当抵扣掉，不该再要求"


@needs_data
def test_each_level_offer_is_a_level_candidate(ctx: CaseContext) -> None:
    """同一般级的多条报价各造一条升级动作，让引擎比价而不是构建时拍一条。"""
    built = actions.build(ctx, "minecraft:ender_pearl")
    level3 = [
        action
        for action in built.bundle.actions
        if action.action_id.startswith("train:3:")
        and action.item == "capability:villager:cleric/3"
    ]
    assert len(level3) >= 2, f"2 级至少两条可升级报价，实际 {len(level3)}"
    # 其中既有花绿宝石的，也有卖货换绿宝石的。
    needs = [{req.item for req in action.requires} for action in level3]
    assert any("minecraft:emerald" in items for items in needs)
    assert any("minecraft:gold_ingot" in items for items in needs)


def test_level_trades_respect_max_uses() -> None:
    """一条报价刷满 `max_uses` 就停止，剩下要换下一条，不能无限刷。"""
    offer = {
        "wants": [{"id": "minecraft:emerald", "count": 1}],
        "gives": {"id": "minecraft:redstone", "count": 2},
        "xp": 2.0,
        "max_uses": 3,
    }
    plan, short = actions._level_trades([offer], 10.0)
    assert plan == [(offer, 3)], "只应刷到上限 3 次"
    assert short == 4.0, "3 次只有 6 点经验，还差 4 点"


def test_level_trades_prefer_fewer_trades() -> None:
    """同样的对价结构下，每次给经验多的先刷，交易次数更少。"""
    cheap = {
        "wants": [{"id": "minecraft:emerald", "count": 1}],
        "gives": {"id": "minecraft:redstone", "count": 2},
        "xp": 5.0,
        "max_uses": 12,
    }
    rich = {
        "wants": [{"id": "minecraft:emerald", "count": 1}],
        "gives": {"id": "minecraft:lapis_lazuli", "count": 1},
        "xp": 10.0,
        "max_uses": 12,
    }
    plan, short = actions._level_trades([cheap, rich], 60.0)
    assert short == 0.0
    assert plan == [(rich, 6)], f"应当用经验多的那条：{plan}"


def test_villager_level_thresholds_are_cumulative() -> None:
    """等级门槛是累计经验：1→5 级分别补 10 / 60 / 80 / 100。"""
    xp_at = actions._xp_at
    assert xp_at(1) == 0.0
    assert xp_at(2) - xp_at(1) == 10.0
    assert xp_at(3) - xp_at(2) == 60.0
    assert xp_at(4) - xp_at(3) == 80.0
    assert xp_at(5) - xp_at(4) == 100.0


@needs_data
def test_low_level_trade_has_no_level_cost(ctx: CaseContext) -> None:
    """1 级交易不用升级，前置里不该出现别的等级的对价。"""
    built = actions.build(ctx, "minecraft:redstone")
    trade = next(
        action
        for action in built.bundle.actions
        if action.action_id.startswith("trade:cleric/1")
        and action.item == "minecraft:redstone"
    )
    assert [req.item for req in trade.requires if req.mode == "per_use"] == [
        "minecraft:emerald"
    ]
