"""前置脆弱点：最优路线里「换掉某个前置的当前来源」要贵多少。

口径：**禁用该前置当前使用的动作，重新求解整条目标路线**。差额里因此包含
固定成本去重与多级依赖的真实变化——段单价是递归定价的结果，改树不改价，
把各层差价相加会失真。

挑选顺序先用局部差额（现成数据，不花求解器），只对前 `limit` 个候选重算，
避免深树里几十个前置各跑一遍。
"""

from __future__ import annotations

from dataclasses import dataclass

from bingo_grading.plan import ActionSet
from bingo_grading.plan import solve as solve_plan
from bingo_grading.plan.explain import PathTree, Step
from bingo_grading.plan.solve import Solved
from bingo_grading.plan.supply import Segment, SupplyError


@dataclass(frozen=True)
class Frontier:
    """一处「换个来源会贵多少」的记录。"""

    item: str
    action: str
    alternative: str
    route_total: float
    delta: float
    delta_ratio: float

    def as_dict(self) -> dict:
        return {
            "item": self.item,
            "action": self.action,
            "alternative": self.alternative,
            "route_total": round(self.route_total, 4),
            "delta": round(self.delta, 4),
            "delta_ratio": round(self.delta_ratio, 4),
        }


def _walk(step: Step, used: dict[str, str], needs: dict[str, float]) -> None:
    for child in step.children:
        # 环/深度截断与 once 占位（action_id 为空）不算「可替换的前置」。
        if child.action_id and not child.note:
            used.setdefault(child.item, child.action_id)
        needs[child.item] = needs.get(child.item, 0.0) + child.need
        _walk(child, used, needs)


def _local_total(seg: Segment, need: float) -> float:
    """这一段凑前 `need` 件的局部总价；只用于挑选候选，不参与差额计算。"""
    return seg.unit_cost * min(need, seg.capacity) + seg.fixed_cost


def frontiers(
    actionset,
    solved: Solved,
    tree: PathTree,
    *,
    limit: int = 8,
    prune_dominated: bool = True,
) -> list[Frontier]:
    """`tree` 里差额最大的前 `limit` 个前置。"""
    if limit <= 0:
        return []
    used: dict[str, str] = {}
    needs: dict[str, float] = {}
    _walk(tree.root, used, needs)

    ranked: list[tuple[float, str, str, Segment]] = []
    for item, action in used.items():
        segments = solved.curve_of(item).segments
        if len(segments) < 2:
            continue
        current = next((seg for seg in segments if seg.action_id == action), None)
        if current is None:
            continue
        need = needs.get(item, 1.0)
        best_alt = min(
            (seg for seg in segments if seg.action_id != action),
            key=lambda seg: _local_total(seg, need),
        )
        if _local_total(best_alt, need) <= _local_total(current, need):
            continue
        ranked.append((_local_total(best_alt, need), item, action, best_alt))
    ranked.sort(key=lambda entry: entry[0], reverse=True)

    results: list[Frontier] = []
    for _local, item, action, _alt in ranked[:limit]:
        work = ActionSet(
            actionset.label,
            tuple(a for a in actionset.actions if a.action_id != action),
        )
        alternate = solve_plan(
            work, tree.item, tree.need, prune_dominated=prune_dominated
        )
        curve = alternate.curve_of(tree.item)
        if not curve.segments:
            continue
        try:
            route_total = curve.cost(tree.need)
        except SupplyError:
            continue
        item_curve = alternate.curve_of(item)
        delta = route_total - tree.total_cost
        if delta <= 0:
            continue
        results.append(
            Frontier(
                item=item,
                action=action,
                alternative=item_curve.head.action_id if item_curve.segments else "",
                route_total=route_total,
                delta=delta,
                delta_ratio=delta / tree.total_cost if tree.total_cost > 0 else 0.0,
            )
        )
    results.sort(key=lambda row: row.delta, reverse=True)
    return results
