"""方案：曲线算完之后长什么样。

解不是一个数字，而是三样东西：

1. **主路线**：曲线最便宜的那几段，也就是 `argmin f(n)`；
2. **备选段**：曲线剩下的段（「便宜的那条用完了」时的替代），以及交叉点；
3. **交叉点**：段与段的交界，即「要几件以上就该换路线」。

「若干条不同路线、内部小绕路被竞争消除」是同一件事的两种读法：
段来自竞争，绕路被剪枝与去重消掉。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from bingo_grading import units

from .actions import MODE_ONCE, ActionSet
from .requires import Charge, dedupe_once, once_cost, per_use_cost
from .supply import EPS, Curve, Segment


class PlanError(ValueError):
    """方案不可行。"""


@dataclass(frozen=True)
class Crossover:
    """段边界：凑够 `after` 件之后，下一个单位改用 `to_action`。"""

    after: float
    from_action: str
    to_action: str
    from_unit: float
    to_unit: float

    def as_dict(self) -> dict:
        return {
            "after": None if math.isinf(self.after) else round(self.after, 4),
            "from": self.from_action,
            "to": self.to_action,
            "from_unit_cost": round(self.from_unit, 6),
            "to_unit_cost": round(self.to_unit, 6),
        }


@dataclass(frozen=True)
class Step:
    """方案里的一步：某个动作做几次。"""

    action_id: str
    item: str
    invocations: float
    produced: float
    local_cost: float
    per_use_cost: float
    requires: tuple[Charge, ...] = ()
    label: str = ""
    source: str = ""
    # 并行来源合成的一步：多个来源同时进行，时间取 max 而不是 sum，
    # 所以 `local_cost` 是曲线上的合成成本，不是各成员成本之和。
    parallel: bool = False

    def as_dict(self) -> dict:
        out = {
            "action_id": self.action_id,
            "item": self.item,
            "invocations": round(self.invocations, 4),
            "produced": round(self.produced, 4),
            "local_cost": round(self.local_cost, 4),
            "per_use_cost": round(self.per_use_cost, 4),
            "requires": [item.as_dict() for item in self.requires],
        }
        if self.parallel:
            out["parallel"] = True
        if self.label:
            out["label"] = self.label
        if self.source:
            out["source"] = self.source
        return out


@dataclass(frozen=True)
class Plan:
    """一次求解的结果。"""

    target: str
    demand: float
    cost: float
    curve_cost: float
    local_cost: float
    per_use_cost: float
    once_cost: float
    once: tuple[Charge, ...] = ()
    shared_saving: float = 0.0
    steps: tuple[Step, ...] = ()
    alternatives: tuple[Segment, ...] = ()
    crossovers: tuple[Crossover, ...] = ()
    missing: str = ""

    @property
    def feasible(self) -> bool:
        return not self.missing and math.isfinite(self.cost)

    @property
    def tier(self) -> int | None:
        """成本落在第几档（`bingo_grading.units.TIER_BOUNDS`）。不可行时为 `None`。"""
        if not self.feasible or self.cost <= 0:
            return None
        return units.tier_of(self.cost)

    @property
    def score(self) -> int | None:
        """成本换成 0–30 分（每 1 分 = 成本 ×√2）。

        口径见 `docs/data/units.md`：
        `score = clamp(round(log2(cost / SCORE_FLOOR) × SCORE_STEP), 0, 30)`。

        目前只有平均成本这一维；「尾部成本」（`p95`）要等数据面补上二阶矩
        才能算，到那时这里是 `max(cost_score, tail_score)`，两个分数并列输出。
        """
        if not self.feasible or self.cost <= 0:
            return None
        return units.score_from_cost(self.cost)

    def as_dict(self, *, detail: bool = True) -> dict:
        out = {
            "target": self.target,
            "demand": self.demand,
            "feasible": self.feasible,
            "cost_tu": None if not math.isfinite(self.cost) else round(self.cost, 4),
            "tier": self.tier,
            "score": self.score,
            "curve_cost_tu": (
                None if not math.isfinite(self.curve_cost) else round(self.curve_cost, 4)
            ),
            "breakdown": {
                "local": round(self.local_cost, 4),
                "per_use": round(self.per_use_cost, 4),
                "once": round(self.once_cost, 4),
                "shared_saving": round(self.shared_saving, 4),
            },
            "crossovers": [item.as_dict() for item in self.crossovers],
            "alternatives": [seg.as_dict() for seg in self.alternatives],
        }
        if self.missing:
            out["missing"] = self.missing
        if detail:
            out["once"] = [item.as_dict() for item in self.once]
            out["steps"] = [step.as_dict() for step in self.steps]
        return out


def _crossover(left: Segment, right: Segment) -> Crossover:
    return Crossover(
        after=left.end,
        from_action=left.action_id,
        to_action=right.action_id,
        from_unit=left.unit_cost,
        to_unit=right.unit_cost,
    )


def _sources(seg: Segment, produced: float) -> tuple[tuple[str, float], ...]:
    """把一段的产出拆给它的来源，按速率（`1/单价`）比例。

    只用于报告「这一段的成本大约由哪几条并行流凑出来」；
    **不能用来重算成本**：并行时两个来源同时在跑，时间取 max 而不是 sum。
    """
    if not seg.members:
        return ((seg.action_id, produced),)
    rates = [(name, 1.0 / cost) for name, cost in seg.members]
    total = sum(rate for _, rate in rates)
    return tuple((name, produced * rate / total) for name, rate in rates)


def build_plan(
    *,
    target: str,
    demand: float,
    curve: Curve,
    actions: ActionSet,
    charges: dict[str, tuple[Charge, ...]] | None = None,
    skip: int = 0,
    curve_of=None,
) -> Plan:
    """按曲线给出 `demand` 件的方案。

    `curve` 必须是**已按层截断**的那条（调用方保证）；`charges` 是每个动作
    前置的定价，用来把成本拆成「本地 / 每次前置 / 一次性前置」。

    `skip` 是「前几段不要」。曲线单价是边际成本，不含 `once` 前置；
    最便宜的那段可能因为固定成本（跑一趟村庄之类）整体上并不便宜，
    所以调用方会逐个跳过便宜段再比全价——见 `solve`。
    """
    if demand <= 0:
        raise PlanError(f"目标数量必须为正：{demand}")
    charges = charges or {}
    crossovers = tuple(
        _crossover(left, right) for left, right in curve.crossovers()
    )
    if not curve:
        return Plan(
            target=target,
            demand=demand,
            cost=math.inf,
            curve_cost=math.inf,
            local_cost=0.0,
            per_use_cost=0.0,
            once_cost=0.0,
            missing=f"{target} 没有任何可用来源",
        )

    used = curve.covering(demand, skip=skip)
    covered = sum(seg.capacity for seg in used)
    if covered + EPS < demand:
        return Plan(
            target=target,
            demand=demand,
            cost=math.inf,
            curve_cost=math.inf,
            local_cost=0.0,
            per_use_cost=0.0,
            once_cost=0.0,
            crossovers=crossovers,
            missing=(
                f"{target} 的可用容量只有 {curve.total_capacity:g} 件，"
                f"不够 {demand:g} 件"
            ),
        )

    steps: list[Step] = []
    once_pool: list[Charge] = []
    local_total = 0.0
    per_use_total = 0.0
    left = demand
    for seg in used:
        produced = min(left, seg.capacity)
        left -= produced
        if seg.members:
            # 并行段：几条流同时在跑，时间取 max 而不是 sum。
            # 所以只能直接取曲线上的合成价，不能把各成员的 cost 累加。
            step_local = produced * seg.unit_cost
            local_total += step_local
            for name, amount in seg.fixed:
                once_pool.append(Charge(name, 1.0, MODE_ONCE, amount, 0.0))
            steps.append(
                Step(
                    action_id=seg.action_id,
                    item=target,
                    invocations=produced,
                    produced=produced,
                    local_cost=step_local,
                    per_use_cost=0.0,
                    requires=(),
                    label=seg.label,
                    source="race",
                    parallel=True,
                )
            )
            continue
        action = actions.get(seg.action_id)
        # `produced` 是**目标物品**的件数，可能不是这个动作的主产物
        # （开一个箱子同时供给黑曜石与燧石）。次数按目标物品的产出算。
        per_invocation = action.effective_yield(target)
        if per_invocation <= EPS:
            raise PlanError(
                f"动作 {action.action_id} 不产出 {target}，曲线与动作集不一致"
            )
        invocations = produced / per_invocation
        action_charges = charges.get(action.action_id, ())
        # 固定成本从**段**上收：它已经含了本动作的 once 前置，
        # 以及前置链上那些一次性投入（同一趟村庄只会出现一次名字）。
        for name, amount in seg.fixed:
            once_pool.append(Charge(name, 1.0, MODE_ONCE, amount, 0.0))
        step_per_use = per_use_cost(action_charges, invocations, curve_of=curve_of)
        if not math.isfinite(step_per_use):
            return Plan(
                target=target,
                demand=demand,
                cost=math.inf,
                curve_cost=math.inf,
                local_cost=0.0,
                per_use_cost=0.0,
                once_cost=0.0,
                crossovers=crossovers,
                missing=(
                    f"动作 {action.action_id} 做 {invocations:g} 次需要的前置"
                    "超出了它的可得总量"
                ),
            )
        step_local = invocations * action.cost
        local_total += step_local
        per_use_total += step_per_use
        steps.append(
            Step(
                action_id=action.action_id,
                item=target,
                invocations=invocations,
                produced=produced,
                local_cost=step_local,
                per_use_cost=step_per_use,
                requires=action_charges,
                label=action.label,
                source=action.source,
            )
        )

    kept_once, saved = dedupe_once(once_pool)
    once_total = once_cost(kept_once)
    curve_cost = 0.0
    left = demand
    for seg in used:
        curve_cost += seg.take(left)
        left -= seg.capacity
    exact = local_total + per_use_total + once_total
    if not math.isfinite(exact):
        return Plan(
            target=target,
            demand=demand,
            cost=math.inf,
            curve_cost=curve_cost,
            local_cost=local_total,
            per_use_cost=per_use_total,
            once_cost=once_total,
            once=kept_once,
            shared_saving=saved,
            steps=tuple(steps),
            crossovers=crossovers,
            missing=f"{target} 的某个前置没有可用来源，成本为无穷",
        )

    used_ids = {seg.action_id for seg in used}
    return Plan(
        target=target,
        demand=demand,
        cost=exact,
        curve_cost=curve_cost,
        local_cost=local_total,
        per_use_cost=per_use_total,
        once_cost=once_total,
        once=kept_once,
        shared_saving=saved,
        steps=tuple(steps),
        alternatives=tuple(
            seg for seg in curve.segments if seg.action_id not in used_ids
        ),
        crossovers=crossovers,
    )
