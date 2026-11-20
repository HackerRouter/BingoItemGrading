"""动作：一条来源的最小可比较形式。

一个**动作**是「做一次」：

| 字段 | 含义 |
|---|---|
| `cost` | 做一次的固定成本（TU）：旅行、开箱、走矿道之外的杂项 |
| `yields` | 做一次的产出向量（物品 → 期望件数） |
| `capacity` | 最多能做几次（`inf` 表示没有上限） |
| `requires` | 必须先到手的东西，带用量与模式 |

产出写成向量而不是单个数字，是因为「挖一块矿同时出石头」「开一个箱子同时出
五六种物品」这些产出不该各付一次旅行成本。成本挂在动作上，按「做几次」计。

`capacity` 记的是**次数**，不是件数。件数上限 = `capacity × yields[item]`。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

MODE_ONCE = "once"
MODE_PER_USE = "per_use"
MODES = (MODE_ONCE, MODE_PER_USE)

# 假物品的前缀。工具、站点、维度入口不是真物品，但它们的成本结构与物品一致，
# 所以照样建模成「某个动作的产出」。报告里靠这个前缀区分。
CAPABILITY_PREFIX = "capability:"


class ActionError(ValueError):
    """动作定义不合法。"""


def is_capability(item: str) -> bool:
    """这条「物品」是不是能力/站点这类假物品。"""
    return item.startswith(CAPABILITY_PREFIX)


@dataclass(frozen=True)
class Requirement:
    """一个前置：某件东西、要多少、按什么模式付。

    - `once`：本方案里只付一次（工具、站点、打火石）。与用几次无关。
    - `per_use`：每次执行动作都要再拿一份（黑曜石、火焰弹、燃料）。

    `forbid` 是**来源前缀黑名单**：这个前置不许用那几条来源满足。
    它不是「这条来源很差」而是「这个用法在游戏里做不到」——例：
    `portal:patch_ruined` 要的是「现成的黑曜石块」，而浇筑出来的是
    「自己造一块」：在废弃传送门已有的框架缺口上倒岩浆与水，
    操作难度和从零浇一整框完全不是一回事，不能让它来抬价。
    黑名单按 `action_id.startswith(prefix)` 匹配。

    `forbid_needs` 是**自举约束**：不许用「不先拿到这些物品就拿不到」的来源。
    例：开下界的门不能用「去下界结构里挖的黑曜石」——那是先有门才能拿到的。
    判断依赖「不用目标时能不能拿到」的不动点，不是看静态依赖图（后者会
    把「铁锭也能从下界猪灵换」当成「铁锭必须下界」）。
    """

    item: str
    qty: float = 1.0
    mode: str = MODE_ONCE
    forbid: tuple[str, ...] = ()
    forbid_needs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.item:
            raise ActionError("前置物品名不能为空")
        if not self.qty > 0:
            raise ActionError(f"前置 {self.item} 的用量必须为正：{self.qty}")
        if self.mode not in MODES:
            raise ActionError(
                f"前置 {self.item} 的模式 {self.mode!r} 不在 {MODES} 内"
            )
        for prefix in self.forbid:
            if not prefix:
                raise ActionError(f"前置 {self.item} 的来源黑名单里不能有空串")
        for name in self.forbid_needs:
            if not name:
                raise ActionError(f"前置 {self.item} 的自举约束里不能有空串")

    def as_dict(self) -> dict:
        out = {"item": self.item, "qty": self.qty, "mode": self.mode}
        if self.forbid:
            out["forbid"] = list(self.forbid)
        if self.forbid_needs:
            out["forbid_needs"] = list(self.forbid_needs)
        return out


@dataclass(frozen=True)
class Action:
    """一次可重复执行的动作。"""

    action_id: str
    item: str
    cost: float
    yields: dict[str, float] = field(default_factory=dict)
    capacity: float = math.inf
    requires: tuple[Requirement, ...] = ()
    label: str = ""
    # 数值出处：`loot_expectation:<subject>` / `structure_content:...` / `calibration`。
    source: str = ""
    # 同一组名 = 这些来源玩家**不知道会先碰到哪个**，跑图时碰到哪个算哪个。
    # 它们的速度相加（`1/μ = Σ1/μᵢ`），而不是「选最便宜的那条」。
    # 例：跑图时碰到村庄就翻箱、碰到废弃传送门就开——两件事不互斥。
    race: str | None = None
    # 可折算成主产物的其它产出：`{物品: 等效件数}`。
    # 例：一箱开出 0.38 锢 + 3.17 金粒，9 粒合 1 锢，那么开箱对「锢」的
    # 有效产出是 `0.38 + 3.17/9`。不这么做的话，引擎会把金粒当成**独立来源**
    # 各算一次全成本，联合产出就被重复计价了。
    equivalents: dict[str, float] = field(default_factory=dict)
    # 动作**自身**的一次性成本（带名字）：到达某层、挖一囗竖井这类。
    # 与 `requires` 里的 `once` 前置不同——那些是「先拿到某物」，这些是
    # 「这个动作本身要做一次的一次性开销」。需求 n 件时只收一次，
    # 否则「挖 N 个矿」会把同一口竖井重挖 N 遍。
    overhead: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        if not self.action_id:
            raise ActionError("动作 ID 不能为空")
        if not self.item:
            raise ActionError(f"动作 {self.action_id} 的主产物不能为空")
        if not math.isfinite(self.cost) or self.cost < 0:
            raise ActionError(f"动作 {self.action_id} 的成本必须有限且非负：{self.cost}")
        if not self.capacity > 0:
            raise ActionError(f"动作 {self.action_id} 的容量必须为正：{self.capacity}")
        if not self.yields:
            raise ActionError(f"动作 {self.action_id} 没有任何产出")
        if self.race is not None and not self.race:
            raise ActionError(f"动作 {self.action_id} 的 race 组名不能为空串（不要并行就写 None）")
        for name, weight in self.equivalents.items():
            if name == self.item:
                raise ActionError(
                    f"动作 {self.action_id} 的 equivalents 里不能含主产物自己"
                )
            if not weight > 0:
                raise ActionError(
                    f"动作 {self.action_id} 的等价折算 {name} 必须为正：{weight}"
                )            # 不在产出里不算错：等价折算表常整表照传（金粒、金块都可能出现），
            # 具体到某个动作时某一项可能压根没产出，自然就是 0 权重。
        for name, amount in self.yields.items():
            if not amount > 0:
                raise ActionError(
                    f"动作 {self.action_id} 的产出 {name} 必须为正：{amount}"
                )
        if self.item not in self.yields:
            raise ActionError(
                f"动作 {self.action_id} 的产出里没有主产物 {self.item}"
            )
        for name, amount in self.overhead:
            if not name:
                raise ActionError(f"动作 {self.action_id} 的固定成本缺少名字")
            if amount < 0:
                raise ActionError(
                    f"动作 {self.action_id} 的固定成本不能为负：{name} = {amount}"
                )
        seen: set[str] = set()
        for req in self.requires:
            if req.item in seen:
                raise ActionError(
                    f"动作 {self.action_id} 对 {req.item} 写了多条前置，"
                    "合并成一条（模式不同要拆成两个动作）"
                )
            seen.add(req.item)
            if req.item in self.yields:
                raise ActionError(
                    f"动作 {self.action_id} 生产 {req.item} 又要求它，自相矛盾"
                )

    # ------------------------------------------------------------ 派生量

    @property
    def primary_yield(self) -> float:
        """做一次能得多少件主产物（不含等价折算）。"""
        return self.yields[self.item]

    def effective_yield(self, item: str) -> float:
        """做一次对 `item` 的**有效产出**：直出 + 可折算的其它产出。

        只有主产物会拿到折算。拿副产物当目标时仍然只是副产物本身的量。
        """
        direct = self.yields.get(item, 0.0)
        if item != self.item:
            return direct
        extra = sum(
            weight * self.yields.get(name, 0.0)
            for name, weight in self.equivalents.items()
        )
        return direct + extra

    @property
    def side_yields(self) -> dict[str, float]:
        """主产物之外的产出。判断「这个动作顺带给了什么」时用。"""
        return {name: amount for name, amount in self.yields.items() if name != self.item}

    def unit_cost(self, surcharge: float = 0.0) -> float:
        """每件**有效**主产物的成本。`surcharge` 是先摊进来的前置成本。"""
        return (self.cost + surcharge) / self.effective_yield(self.item)

    def item_capacity(self) -> float:
        """这个动作总共最多能给出多少件主产物（含等价折算）。"""
        return self.capacity * self.effective_yield(self.item)

    def overhead_total(self) -> float:
        """动作自身的一次性成本合计（不含 `requires` 里的一次性前置）。"""
        return sum(amount for _, amount in self.overhead)

    def requirement_items(self) -> frozenset[str]:
        return frozenset(req.item for req in self.requires)

    def as_dict(self, *, full: bool = False) -> dict:
        """`full=True` 保留完整浮点，供落盘复用（图必须逐位往返）。

        默认对数值做舍入，因为这份输出主要给人读；落盘时舍入会让
        `whole_cost_tu` 的最后一位漂移，两种查询模式就对不上了。
        `overhead` 写有序对而不是对象：同名固定成本可以出现多次
        （不同纵段的竖井各收一次），写成对象会静默吞掉后一条。
        """
        number = (lambda value: value) if full else (lambda value: round(value, 4))
        weight = (lambda value: value) if full else (lambda value: round(value, 6))
        out = {
            "action_id": self.action_id,
            "item": self.item,
            "cost": number(self.cost),
            "yields": {
                name: weight(value) for name, value in sorted(self.yields.items())
            },
            "capacity": None if math.isinf(self.capacity) else self.capacity,
            "requires": [req.as_dict() for req in self.requires],
        }
        if self.label:
            out["label"] = self.label
        if self.source:
            out["source"] = self.source
        if self.race is not None:
            out["race"] = self.race
        if self.equivalents:
            out["equivalents"] = {
                name: weight(value)
                for name, value in sorted(self.equivalents.items())
            }
        if self.overhead:
            out["overhead"] = [[name, weight(amount)] for name, amount in self.overhead]
        return out

    @classmethod
    def from_dict(cls, raw: dict) -> "Action":
        capacity = raw.get("capacity")
        return cls(
            action_id=raw["action_id"],
            item=raw["item"],
            cost=raw["cost"],
            yields=dict(raw.get("yields") or {}),
            capacity=math.inf if capacity is None else capacity,
            requires=tuple(
                Requirement(
                    item=entry["item"],
                    qty=entry.get("qty", 1.0),
                    mode=entry.get("mode", MODE_ONCE),
                    forbid=tuple(entry.get("forbid") or ()),
                    forbid_needs=tuple(entry.get("forbid_needs") or ()),
                )
                for entry in raw.get("requires") or ()
            ),
            label=raw.get("label", ""),
            source=raw.get("source", ""),
            race=raw.get("race"),
            equivalents=dict(raw.get("equivalents") or {}),
            overhead=tuple((name, amount) for name, amount in raw.get("overhead") or ()),
        )


@dataclass(frozen=True)
class ActionSet:
    """一组动作，按主产物索引。"""

    label: str
    actions: tuple[Action, ...]

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for action in self.actions:
            if action.action_id in seen:
                raise ActionError(f"动作 ID 重复：{action.action_id}")
            seen.add(action.action_id)

    def by_item(self) -> dict[str, list[Action]]:
        index: dict[str, list[Action]] = {}
        for action in self.actions:
            index.setdefault(action.item, []).append(action)
        return index

    def items(self) -> list[str]:
        return sorted({action.item for action in self.actions})

    def produced_items(self) -> list[str]:
        """所有出现过的产出名，含副产物。"""
        return sorted({name for action in self.actions for name in action.yields})

    def get(self, action_id: str) -> Action:
        for action in self.actions:
            if action.action_id == action_id:
                return action
        raise ActionError(f"没有动作 {action_id!r}")

    def without(self, *action_ids: str) -> "ActionSet":
        """去掉若干动作。测试「少一条来源会怎样」时用，不改原集合。"""
        drop = set(action_ids)
        missing = drop - {action.action_id for action in self.actions}
        if missing:
            raise ActionError(f"要去掉的动作不存在：{sorted(missing)}")
        return ActionSet(
            label=self.label,
            actions=tuple(a for a in self.actions if a.action_id not in drop),
        )

    def as_dict(self, *, full: bool = False) -> dict:
        return {
            "label": self.label,
            "actions": [action.as_dict(full=full) for action in self.actions],
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "ActionSet":
        return cls(
            label=raw.get("label", ""),
            actions=tuple(Action.from_dict(entry) for entry in raw.get("actions") or ()),
        )

    def summary(self) -> dict:
        return {
            "label": self.label,
            "actions": len(self.actions),
            "items": len(self.items()),
            "max_capacity": sum(
                1 for action in self.actions if not math.isfinite(action.capacity)
            ),
        }
