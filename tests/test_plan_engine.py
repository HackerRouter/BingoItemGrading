"""供给曲线的规则（不需要统计快照）。

这里每条测试都对应 `docs/design-route-competition.md` 里的一条判据。
"""

from __future__ import annotations

import math

import pytest

from bingo_grading.plan import (
    MODE_ONCE,
    MODE_PER_USE,
    Action,
    ActionError,
    ActionSet,
    Curve,
    Requirement,
    Segment,
    build_schedule,
    merge,
    prune,
    solve,
)
from bingo_grading.plan.supply import invocations_for

# ---------------------------------------------------------------- 曲线本身


def test_curve_sorts_by_unit_cost() -> None:
    curve = merge(
        Curve.of([Segment("b", 9.0, 2.0)]),
        Curve.of([Segment("a", 3.0, 5.0)]),
    )
    assert [seg.action_id for seg in curve.segments] == ["a", "b"]
    assert [seg.start for seg in curve.segments] == [0.0, 5.0]


def test_curve_cost_covers_capacity_then_fails() -> None:
    curve = Curve.of([Segment("a", 2.0, 3.0)])
    assert curve.cost(0) == 0.0
    assert curve.cost(3) == pytest.approx(6.0)
    assert curve.cost(4) == math.inf


def test_curve_breaks_are_the_crossover_points() -> None:
    curve = merge(
        Curve.of([Segment("a", 2.0, 3.0)]),
        Curve.of([Segment("b", 5.0, 10.0)]),
    )
    assert curve.breaks() == (3.0,)


def test_compose_applies_ratio_and_fixed_cost() -> None:
    """串联：每 2 件成品要 1 件输入，每次还要 1 TU。"""
    parent = Curve.of([Segment("ore", 6.0, 10.0)])
    child = parent.compose(ratio=2.0, fixed=1.0)
    # (6 + 1) / 2 = 3.5 每件；容量翻倍
    assert child.segments[0].unit_cost == pytest.approx(3.5)
    assert child.total_capacity == pytest.approx(20.0)


def test_curve_rejects_non_positive_capacity() -> None:
    with pytest.raises(Exception):
        Segment("a", 1.0, 0.0)


# ---------------------------------------------------------------- 动作与剪枝


def test_joint_output_invocations_take_max() -> None:
    """一次动作同时出 A 与 B，次数取最大比例，不相加。"""
    action = Action("box", "a", 2.0, {"a": 2.0, "b": 4.0})
    assert invocations_for(action, {"a": 4.0, "b": 8.0}) == pytest.approx(2.0)
    assert invocations_for(action, {"a": 4.0, "b": 4.0}) == pytest.approx(2.0)


def test_prune_drops_dominated_source() -> None:
    """更贵 + 容量更小 + 前置更多的来源直接出局。"""
    good = Action("good", "x", 4.0, {"x": 1.0})
    bad = Action(
        "bad",
        "x",
        8.0,
        {"x": 1.0},
        capacity=2.0,
        requires=(Requirement("capability:pick", 1.0, MODE_ONCE),),
    )
    result = prune([good, bad])
    assert [action.action_id for action in result.kept] == ["good"]
    assert result.dropped == (("bad", "good"),)


def test_prune_keeps_one_of_two_identical_sources() -> None:
    """互支配时不能两条都判掉，否则来源会凭空消失。"""
    left = Action("a", "x", 4.0, {"x": 1.0})
    right = Action("b", "x", 4.0, {"x": 1.0})
    result = prune([left, right])
    assert len(result.kept) == 1
    assert result.kept[0].action_id == "a"


def test_prune_keeps_more_expensive_but_richer_side_yields() -> None:
    """顺带出别的东西的来源不算被支配。"""
    plain = Action("plain", "x", 2.0, {"x": 1.0})
    rich = Action("rich", "x", 3.0, {"x": 1.0, "y": 1.0})
    result = prune([plain, rich])
    assert {action.action_id for action in result.kept} == {"plain", "rich"}


def test_prune_keeps_cheaper_unit_with_dearer_overhead() -> None:
    """单价低但到达贵 与 单价高但到达便宜 各有更优区间，不能互相剪掉。

    粘土的三种采法就是这样：捡地表河床（找首片便宜、单价略高）与
    下洞穴挖（到达贵、单价略低）。只比单价会把小需求量下正确的最优剪掉。
    """
    cheap_unit = Action(
        "cave", "x", 2.0, {"x": 1.0}, overhead=(("cave:x", 5.0),)
    )
    cheap_overhead = Action(
        "surface", "x", 3.0, {"x": 1.0}, overhead=(("find:x", 1.0),)
    )
    result = prune([cheap_unit, cheap_overhead])
    assert {action.action_id for action in result.kept} == {"cave", "surface"}


# ---------------------------------------------------------------- 供给竞争


def test_cheap_source_is_used_first_then_next_segment() -> None:
    """判据 1/4：曲线解 = 按单价排序的贪心解；容量用满就换段。"""
    actionset = ActionSet(
        "t",
        (
            Action("slow", "x", 10.0, {"x": 1.0}),
            Action("fast", "x", 6.0, {"x": 1.0}, capacity=3.0),
        ),
    )
    solved = solve(actionset, "x", 5.0, prune_dominated=False)
    assert solved.plan.cost == pytest.approx(3 * 6.0 + 2 * 10.0)
    assert [step.action_id for step in solved.plan.steps] == ["fast", "slow"]
    assert solved.plan.crossovers[0].after == pytest.approx(3.0)
    assert solved.plan.crossovers[0].to_action == "slow"


def test_capacity_one_switches_at_the_second_unit() -> None:
    """判据 4：便宜来源只有 1 件产能，第 2 件就该切段。"""
    actionset = ActionSet(
        "t",
        (
            Action("one", "x", 1.0, {"x": 1.0}, capacity=1.0),
            Action("many", "x", 5.0, {"x": 1.0}),
        ),
    )
    solved = solve(actionset, "x", 2.0, prune_dominated=False)
    assert solved.plan.cost == pytest.approx(6.0)
    assert [step.produced for step in solved.plan.steps] == [1.0, 1.0]


def test_demand_beyond_capacity_is_infeasible() -> None:
    actionset = ActionSet("t", (Action("one", "x", 1.0, {"x": 1.0}, capacity=1.0),))
    solved = solve(actionset, "x", 2.0)
    assert not solved.plan.feasible
    assert "容量" in solved.plan.missing


def test_joint_yield_feeds_every_item_curve() -> None:
    """一个动作对每一样产出都贡献曲线，不能只算主产物。"""
    actionset = ActionSet(
        "t",
        (
            Action("box", "a", 4.0, {"a": 1.0, "b": 0.5}),
            Action(
                "craft",
                "target",
                0.0,
                {"target": 1.0},
                requires=(Requirement("b", 1.0),),
            ),
        ),
    )
    solved = solve(actionset, "target", 1.0)
    assert solved.plan.feasible
    # b 的曲线也来自同一个开箱动作：0.5 个/次 → 单价 8 TU
    assert [seg.action_id for seg in solved.curve_of("b").segments] == ["box"]
    assert solved.curve_of("b").cost(1.0) == pytest.approx(8.0)
    assert solved.plan.cost == pytest.approx(8.0)
    # 直接要副产物 b 时，次数按 b 的产出算（第 1 件就要开 2 个箱子）
    direct = solve(actionset, "b", 1.0)
    assert direct.plan.steps[0].invocations == pytest.approx(2.0)
    assert direct.plan.cost == pytest.approx(8.0)


# ---------------------------------------------------------------- 分层


def test_levels_increase_along_the_chain() -> None:
    actionset = ActionSet(
        "t",
        (
            Action("log", "wood", 1.0, {"wood": 1.0}),
            Action("plank", "planks", 0.1, {"planks": 1.0}, requires=(Requirement("wood"),)),
            Action("stick", "stick", 0.1, {"stick": 1.0}, requires=(Requirement("planks"),)),
        ),
    )
    schedule = build_schedule(actionset)
    assert schedule.tier_of("wood") == 0
    assert schedule.tier_of("planks") == 1
    assert schedule.tier_of("stick") == 2
    assert schedule.max_level == 2


def test_cycle_is_unreachable_and_reported() -> None:
    """纯循环拿不到层号，并且能给出环的证据链。"""
    actionset = ActionSet(
        "t",
        (
            Action("to_a", "a", 1.0, {"a": 1.0}, requires=(Requirement("b"),)),
            Action("to_b", "b", 1.0, {"b": 1.0}, requires=(Requirement("a"),)),
        ),
    )
    schedule = build_schedule(actionset)
    assert schedule.item_tier == {}
    assert len(schedule.cycles) == 1
    assert schedule.cycles[0].chain == ("a", "b", "a")
    assert {item.action_id for item in schedule.unreachable} == {"to_a", "to_b"}


def test_requirement_from_a_later_level_is_not_used() -> None:
    """核心约束：动作只能用它**自己那一层之前**的来源。

    这里有两份「火花」：早的那份贵、晚的那份便宜。门在第 1 层，
    所以它只能看到早的那份——晚的那份要靠门才拿得到。
    """
    actionset = ActionSet(
        "t",
        (
            Action("spark_early", "spark", 10.0, {"spark": 1.0}),
            Action("gate", "gate", 1.0, {"gate": 1.0}, requires=(Requirement("spark"),)),
            Action(
                "spark_late",
                "spark",
                1.0,
                {"spark": 1.0},
                requires=(Requirement("gate_afterlife"),),
            ),
            Action(
                "afterlife",
                "gate_afterlife",
                1.0,
                {"gate_afterlife": 1.0},
                requires=(Requirement("gate"),),
            ),
        ),
    )
    solved = solve(actionset, "gate", 1.0, prune_dominated=False)
    assert solved.plan.feasible
    # 门只能用 10 TU 的那份火花，不能用 1 TU 的
    assert solved.plan.cost == pytest.approx(11.0)
    assert solved.plan.steps[0].requires[0].via == "spark_early"
    # 顶层曲线里两份都在。晚的那份要靠一座门（11）再加 1 的工序：拿 1 件要 13、
    # 拿 2 件要 13 + 10（第二件起走早火花）。
    curve = solved.curve_of("spark")
    assert {seg.action_id for seg in curve.segments} == {"spark_early", "spark_late"}
    assert curve.cost(1.0) == pytest.approx(10.0)
    # 绕一圈的门路：固定 12（ afterlife + 门）+ 每件 1，拿 2 件要 14
    assert curve.cost(2.0) == pytest.approx(14.0)
    late = next(seg for seg in curve.segments if seg.action_id == "spark_late")
    assert curve.cost(1.0) < late.fixed_cost + late.unit_cost


# ---------------------------------------------------------------- 前置模式


def _tool_actionset() -> ActionSet:
    return ActionSet(
        "t",
        (
            Action("buy_tool", "capability:tool", 3.0, {"capability:tool": 1.0}),
            Action("get_mat", "mat", 5.0, {"mat": 1.0}),
            Action(
                "make_a",
                "thing",
                2.0,
                {"thing": 1.0},
                capacity=2.0,
                requires=(
                    Requirement("capability:tool", 1.0, MODE_ONCE),
                    Requirement("mat", 2.0, MODE_PER_USE),
                ),
            ),
            Action(
                "make_b",
                "thing",
                20.0,
                {"thing": 1.0},
                requires=(Requirement("capability:tool", 1.0, MODE_ONCE),),
            ),
        ),
    )


def test_once_requirement_is_charged_once() -> None:
    """判据 5：同一个 `once` 前置在方案里只计一次。"""
    solved = solve(_tool_actionset(), "thing", 3.0, prune_dominated=False)
    breakdown = solved.plan.as_dict()["breakdown"]
    assert breakdown["once"] == pytest.approx(3.0)
    # 两个动作各报了一次 3 TU 的前置，去重省下 3 TU
    assert breakdown["shared_saving"] == pytest.approx(3.0)


def test_per_use_requirement_scales_with_invocations() -> None:
    """判据 5：`per_use` 随次数线性。"""
    solved = solve(_tool_actionset(), "thing", 2.0, prune_dominated=False)
    assert solved.plan.per_use_cost == pytest.approx(2 * 2 * 5.0)
    once = solve(_tool_actionset(), "thing", 1.0, prune_dominated=False)
    assert once.plan.per_use_cost == pytest.approx(2 * 5.0)


def test_requirement_without_producer_is_unreachable() -> None:
    """前置没有任何生产者的动作拿不到层号，报在 `unreachable` 里。"""
    actionset = ActionSet(
        "t",
        (
            Action("make", "x", 1.0, {"x": 1.0}, requires=(Requirement("ghost"),)),
        ),
    )
    solved = solve(actionset, "x", 1.0, prune_dominated=False)
    assert not solved.plan.feasible
    assert [item.action_id for item in solved.schedule.unreachable] == ["make"]
    assert solved.schedule.unreachable[0].missing == ("ghost",)
    assert solved.schedule.unreachable[0].cycle is None


# ---------------------------------------------------------------- 输入校验


def test_action_rejects_self_requirement() -> None:
    with pytest.raises(ActionError):
        Action("a", "x", 1.0, {"x": 1.0}, requires=(Requirement("x"),))


def test_action_rejects_duplicate_requirements() -> None:
    with pytest.raises(ActionError):
        Action(
            "a",
            "x",
            1.0,
            {"x": 1.0},
            requires=(Requirement("y"), Requirement("y", 2.0)),
        )


def test_actionset_rejects_duplicate_ids() -> None:
    with pytest.raises(ActionError):
        ActionSet("t", (Action("a", "x", 1.0, {"x": 1.0}), Action("a", "y", 1.0, {"y": 1.0})))


def test_actionset_without_removes_actions() -> None:
    actionset = ActionSet(
        "t", (Action("a", "x", 1.0, {"x": 1.0}), Action("b", "x", 2.0, {"x": 1.0}))
    )
    assert [action.action_id for action in actionset.without("b").actions] == ["a"]


# ---------------------------------------------------------------- 回归：成本最优性


def test_curve_cost_can_skip_a_middle_segment() -> None:
    """固定成本使「跳过中间段」可能最优：只枚举后缀会漏解。"""
    s1 = Segment("s1", 1.0, 5.0)
    s2 = Segment("s2", 3.0, 5.0)
    s3 = Segment("s3", 1.5, math.inf, fixed=(("cap:x", 5.0),))
    curve = Curve.of([s1, s2, s3])
    # 5 件走 s1、5 件走 s3：5 + 7.5 + 5 = 17.5，比 s1 + s2 的 20 便宜
    assert curve.cost(10.0) == pytest.approx(17.5)
    assert {seg.action_id for seg in curve.covering(10.0)} == {"s1", "s3"}


def test_prune_compares_item_capacity_not_invocations() -> None:
    """容量按件数比：一次出 5 件的动作不能被「一次出 1 件」的判掉。"""
    small = Action("small", "x", 1.0, {"x": 1.0}, capacity=10.0)
    bulk = Action("bulk", "x", 10.0, {"x": 5.0}, capacity=10.0)
    result = prune([small, bulk])
    assert {action.action_id for action in result.kept} == {"small", "bulk"}


def test_per_use_requirement_beyond_capacity_is_infeasible() -> None:
    """前置只够 3 件时，要做 10 次的动作必须判不可行，不能按边际外推。"""
    actionset = ActionSet(
        "t",
        (
            Action("src", "p", 1.0, {"p": 1.0}, capacity=3.0),
            Action(
                "use",
                "x",
                0.0,
                {"x": 1.0},
                capacity=10.0,
                requires=(Requirement("p", 1.0, MODE_PER_USE),),
            ),
        ),
    )
    solved = solve(actionset, "x", 10.0, prune_dominated=False)
    assert not solved.plan.feasible
    assert "超出" in solved.plan.missing


def test_action_overhead_is_charged_once() -> None:
    """动作自带的一次性成本（如竖井）按件数摊薄，不随次数重复收。"""
    action = Action("dig", "x", 2.0, {"x": 1.0}, overhead=(("reach:y0", 3.0),))
    solved = solve(ActionSet("t", (action,)), "x", 10.0, prune_dominated=False)
    assert solved.plan.cost == pytest.approx(2.0 * 10 + 3.0)
