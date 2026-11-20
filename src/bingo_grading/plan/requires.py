"""把前置折算成钱。

前置不是可行性门槛，也不是评分维度，而是**要花钱的东西**，只是付法有两种：

| 模式 | 含义 | 例 |
|---|---|---|
| `once` | 同一方案里只付一次 | 钻石镐、打火石、站点 |
| `per_use` | 每做一次动作再付一份 | 黑曜石 ×10、火焰弹、燃料 |

不模拟耐久：一把镐不按「能挖多少块」衰减，所以工具永远是 `once`。
工具等级是硬约束（钻石矿要铁镐），但它同时也是一个物品，价格照样走供给曲线。

去重放在**方案级**：两个分支都要铁镐时只付一次。曲线按「第一件全额、
后续单价」的近似把这个差异记在单价里，方案级去重只减不增，两者都输出，
差额就是共享前置省下来的钱。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from .actions import MODE_ONCE, MODE_PER_USE, Action, Requirement
from .supply import Curve, merge_fixed


class RequirementError(ValueError):
    """前置在某层拿不到任何来源。"""


@dataclass(frozen=True)
class Charge:
    """一个前置被折算成的钱。"""

    item: str
    qty: float
    mode: str
    # 取 `qty` 件的**总价**（含这条前置来源自己的固定成本）。一次性的东西付这笔。
    cost: float
    # 其中随件数增长的那部分（不含固定成本）；重复取货时只有这部分会再付。
    marginal: float
    # 这笔价格里含的固定成本，带物品名：`(("capability:village", 2.42), ...)`。
    # 带名字才能在跨层传递时去重——同名的就是同一笔一次性投入。
    fixed_items: tuple[tuple[str, float], ...] = ()
    # 这个价格用了哪一段（也就是「走的是哪条来源」），报告里指路用。
    via: str = ""
    # 定价时用到的预算（前置取自 `budget` 那一层的曲线）。
    budget: int | None = None
    # 这个前置禁用的来源前缀（见 `Requirement.forbid`）。重算时还得带着它，
    # 否则「按总量重新走一遍曲线」会把被禁的来源又算回来。
    forbid: tuple[str, ...] = ()

    @property
    def finite(self) -> bool:
        return math.isfinite(self.cost)

    @property
    def fixed(self) -> float:
        """这条前置里的固定成本部分。"""
        if not math.isfinite(self.cost):
            return self.cost
        return sum(amount for _, amount in self.fixed_items)

    def as_dict(self) -> dict:
        out = {
            "item": self.item,
            "qty": self.qty,
            "mode": self.mode,
            "cost": None if not self.finite else round(self.cost, 4),
            "marginal": None if not math.isfinite(self.marginal) else round(self.marginal, 4),
            "via": self.via,
            "budget": self.budget,
        }
        if self.forbid:
            out["forbid"] = list(self.forbid)
        return out


def charge(
    requirement: Requirement,
    *,
    curve: Curve,
    budget: int | None = None,
    forbid: tuple[str, ...] = (),
) -> Charge:
    """给一个前置定价。`curve` 必须是**只用了上一档预算**得到的那条。

    `forbid` 是求解器额外加的黑名单（与 `Requirement.forbid` 合并）：
    它不写在动作里，因为它是**环**推出来的——见 `solve._ring_forbid`。
    """
    prefixes = tuple(requirement.forbid) + tuple(forbid)
    if prefixes:
        curve = curve.excluding(*prefixes)
    if not curve:
        raise RequirementError(
            f"前置 {requirement.item} 在预算 {budget} 之前没有任何来源"
            + (f"（已排除 {', '.join(prefixes)}）" if prefixes else "")
        )
    # 一次 `_pick` 拿齐四项：`cost()` / `marginal_cost()` / `_pick()` /
    # `segment_at()` 各自内部都要枚举一遍段的子集，分开调就是四次重复计算——
    # `_pick` 是求解里最热的函数，这一处合并直接省掉四分之三。
    total, marginal, used, fixed_items = curve._pick(requirement.qty)
    cost = total
    via = used[-1].action_id if used else ""
    return Charge(
        item=requirement.item,
        qty=requirement.qty,
        mode=requirement.mode,
        cost=cost,
        marginal=marginal,
        fixed_items=fixed_items if math.isfinite(cost) else (),
        via=via,
        budget=budget,
        forbid=prefixes,
    )


def charge_all(
    action: Action,
    *,
    curve_of,
    budget: int | None = None,
    forbid_of=None,
) -> tuple[Charge, ...]:
    """把一个动作的全部前置定价。

    `forbid_of(requirement)` 返回该前置要额外排除的来源 id（自举约束解析出来的）。
    """
    return tuple(
        charge(
            req,
            curve=curve_of(req.item),
            budget=budget,
            forbid=tuple(forbid_of(req)) if forbid_of is not None else (),
        )
        for req in action.requires
    )


def per_invocation_cost(charges: Iterable[Charge]) -> float:
    """每做一次动作额外要付的**边际**钱。

    只算 `per_use` 前置，且只算它们的边际部分：

    - `once` 前置（做一套工具、解锁一个状态）整笔都是固定的，不进单价；
    - `per_use` 前置里也有固定成本（比如第一次去河边），那部分只付一次，
      同样不进单价。

    固定成本由曲线段上的 `fixed_cost` 承载（`Curve.cost` 在方案层收一次），
    所以「单价」是纯粹的边际成本——需求 n 件时就是 `n × 单价 + 固定`。
    """
    return sum(item.marginal for item in charges if item.mode == MODE_PER_USE)


def fixed_cost_of(charges: Iterable[Charge]) -> tuple[tuple[str, float], ...]:
    """这个动作**第一次**做时要付的固定成本（带名字，同名合并）。

    `once` 前置全额 + `per_use` 前置里的固定部分。带名字的原因是：
    同一趟村庄可能在「取材料」和「用材料」两处各出现一次，但它是同一笔钱。
    """
    groups: list[tuple[str, float]] = []
    for item in charges:
        if item.mode == MODE_ONCE:
            groups.append(((item.item, item.cost),))
        else:
            groups.append(item.fixed_items)
    return merge_fixed(*groups)


def per_use_cost(
    charges: Iterable[Charge],
    invocations: float = 1.0,
    *,
    curve_of=None,
) -> float:
    """做 `invocations` 次动作，`per_use` 前置的**总**花费。

    两种口径：

    - 不给 `curve_of`：按「每次的边际」线性外推。这是构图时的近似（段单价必须
      是常数），只适合需求远小于前置容量的情形���
    - 给 `curve_of`：按实际总量 `qty × invocations` **重新走一遍供给曲线**。
      便宜来源用完后会自然切到更贵的段；总量超过全部容量时返回 `inf`——
      动作在这么多用量下根本做不了，不能按边际外推当成可行。
    """
    total = 0.0
    for item in charges:
        if item.mode != MODE_PER_USE:
            continue
        if curve_of is None:
            total += invocations * item.marginal
            continue
        needed = item.qty * invocations
        curve = curve_of(item.item)
        if item.forbid:
            curve = curve.excluding(*item.forbid)
        if not curve:
            return math.inf
        price = curve.cost(needed)
        if not math.isfinite(price):
            return math.inf
        # 固定成本已经由曲线段的 `fixed` 收过一份，这里只补增量。
        already_fixed = sum(amount for _, amount in item.fixed_items)
        total += max(0.0, price - already_fixed)
    return total


def dedupe_once(charges: Iterable[Charge]) -> tuple[tuple[Charge, ...], float]:
    """方案级去重：同一个 `once` 前置只付一次，取最大用量那一份。

    返回 `(保留的一次性前置, 省下来的钱)`。
    """
    best: dict[str, Charge] = {}
    total = 0.0
    for item in charges:
        if item.mode != MODE_ONCE:
            continue
        total += item.cost
        current = best.get(item.item)
        if current is None or item.qty > current.qty:
            best[item.item] = item
    kept = tuple(best[key] for key in sorted(best))
    saved = total - sum(item.cost for item in kept)
    return kept, saved


def once_cost(charges: Iterable[Charge]) -> float:
    return sum(item.cost for item in charges if item.mode == MODE_ONCE)
