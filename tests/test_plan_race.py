"""并行来源（`race`）：跑图时碰到哪个算哪个，速度相加。

判据来自 `docs/design-route-competition.md`：
互斥来源取 min，**并行来源速率相加** `1/μ = Σ1/μᵢ`。
"""

from __future__ import annotations

import pytest

from bingo_grading.plan import (
    Action,
    ActionSet,
    Requirement,
    Segment,
    SolveError,
    SupplyError,
    prune,
    solve,
)
from bingo_grading.plan.supply import merge_race


def _race_set(*actions: Action) -> ActionSet:
    return ActionSet("race", tuple(actions))


def test_race_adds_rates_instead_of_taking_min() -> None:
    """10 分钟一件与 20 分钟一件并行 → 6.67 分钟，不是 10。"""
    actionset = _race_set(
        Action("slow", "x", 20.0, {"x": 1.0}, race="surface"),
        Action("fast", "x", 10.0, {"x": 1.0}, race="surface"),
    )
    solved = solve(actionset, "x", 1.0, prune_dominated=False)
    assert solved.plan.cost == pytest.approx(1.0 / (1 / 10 + 1 / 20))
    assert solved.plan.cost < 10.0


def test_mutually_exclusive_sources_still_take_min() -> None:
    """同样的两个动作，不标 race 就是「选一条走」→ 10 分钟。"""
    actionset = _race_set(
        Action("slow", "x", 20.0, {"x": 1.0}),
        Action("fast", "x", 10.0, {"x": 1.0}),
    )
    solved = solve(actionset, "x", 1.0)
    assert solved.plan.cost == pytest.approx(10.0)
    assert [step.action_id for step in solved.plan.steps] == ["fast"]


def test_race_scales_linearly_with_demand() -> None:
    actionset = _race_set(
        Action("slow", "x", 20.0, {"x": 1.0}, race="surface"),
        Action("fast", "x", 10.0, {"x": 1.0}, race="surface"),
    )
    unit = 1.0 / (1 / 10 + 1 / 20)
    assert solve(actionset, "x", 3.0).plan.cost == pytest.approx(3 * unit)


def test_race_capacities_add_up() -> None:
    actionset = _race_set(
        Action("a", "x", 10.0, {"x": 1.0}, capacity=1.0, race="g"),
        Action("b", "x", 20.0, {"x": 1.0}, capacity=1.0, race="g"),
    )
    assert solve(actionset, "x", 2.0).plan.feasible
    short = solve(actionset, "x", 3.0)
    assert not short.plan.feasible
    assert "容量" in short.plan.missing


def test_race_step_is_marked_parallel() -> None:
    actionset = _race_set(
        Action("slow", "x", 20.0, {"x": 1.0}, race="g"),
        Action("fast", "x", 10.0, {"x": 1.0}, race="g"),
    )
    step = solve(actionset, "x", 1.0).plan.steps[0]
    assert step.parallel
    assert step.action_id.startswith("race[")
    assert step.local_cost == pytest.approx(step.produced * 1.0 / (1 / 10 + 1 / 20))


def test_race_members_must_share_requirements() -> None:
    """前置不同时不能速率相加：共享的前置会被重复计一次。"""
    actionset = _race_set(
        Action("tool", "tool", 1.0, {"tool": 1.0}),
        Action("a", "x", 10.0, {"x": 1.0}, race="g", requires=(Requirement("tool", 1.0),)),
        Action("b", "x", 20.0, {"x": 1.0}, race="g", requires=(Requirement("tool", 2.0),)),
    )
    with pytest.raises(SolveError, match="前置不一致"):
        solve(actionset, "x", 1.0, prune_dominated=False)


def test_race_members_are_never_pruned() -> None:
    """并行语义下「更贵」不是「更差」——贵的那条仍在提供一份额外速率。"""
    fast = Action("fast", "x", 10.0, {"x": 1.0}, race="g")
    slow = Action("slow", "x", 20.0, {"x": 1.0}, race="g")
    assert not prune([fast, slow]).dropped
    # 对照组：不标 race 时慢的被剪
    plain = prune([Action("fast", "x", 10.0, {"x": 1.0}), Action("slow", "x", 20.0, {"x": 1.0})])
    assert plain.dropped == (("slow", "fast"),)


def test_cheaper_single_source_beats_a_race_group() -> None:
    actionset = _race_set(
        Action("slow", "x", 20.0, {"x": 1.0}, race="g"),
        Action("fast", "x", 10.0, {"x": 1.0}, race="g"),
        Action("cheap", "x", 4.0, {"x": 1.0}),
    )
    solved = solve(actionset, "x", 1.0, prune_dominated=False)
    assert solved.plan.cost == pytest.approx(4.0)
    assert solved.plan.steps[0].parallel is False


def test_zero_cost_race_member_is_rejected() -> None:
    """零成本成员的速率是无限的，没法按速率分摊件数。"""
    with pytest.raises(SupplyError):
        merge_race([Segment("a", 0.0, 1.0), Segment("b", 5.0, 1.0)])

