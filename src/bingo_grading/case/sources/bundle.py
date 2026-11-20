"""通用装配：动作包、秒→TU、确定性转换、能力站点。"""

from __future__ import annotations


from dataclasses import dataclass, field
from bingo_grading import units
from bingo_grading.case.context import CaseContext, Sourced
from bingo_grading.plan import Action, ActionSet, Requirement
from bingo_grading.plan.actions import MODE_ONCE, MODE_PER_USE




@dataclass
class ActionBundle:
    """一个目标的动作集 + 拼装过程中的说明。

    动作工厂（`case/sources/*`）与自动入口（`sources/actions/`）都返回这个类型，
    CLI 与测试口径统一。`extras` 放各来源族特有的诊断（例如门框匹配明细），
    不污染公共字段。
    """

    label: str
    actions: list[Action] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    provenance: dict[str, Sourced] = field(default_factory=dict)
    extras: dict[str, object] = field(default_factory=dict)

    def add(self, *actions: Action | None) -> None:
        for action in actions:
            if action is not None:
                self.actions.append(action)

    def actionset(self) -> ActionSet:
        return ActionSet(label=self.label, actions=tuple(self.actions))

    def note(self, text: str) -> None:
        self.assumptions.append(text)

    def record(self, key: str, sourced: Sourced) -> None:
        self.provenance[key] = sourced




def seconds(value: float) -> float:
    """秒 → TU。案例里的耗时常量一律走这里，避免各处各写一遍除法。"""
    return value / units.SECONDS_PER_TU




# ---------------------------------------------------------------- 合成 / 熔炼


def craft(
    bundle: ActionBundle,
    *,
    action_id: str,
    yields: dict[str, float],
    inputs: dict[str, float],
    cost: float = 0.0,
    label: str = "",
    source: str = "crafting",
) -> Action:
    """一条确定性转换（配方、拆解、熔炼的固定部分）。"""
    item = max(yields, key=lambda name: yields[name])
    return Action(
        action_id=action_id,
        item=item,
        cost=cost,
        yields=dict(yields),
        requires=tuple(
            Requirement(name, amount, MODE_PER_USE) for name, amount in inputs.items()
        ),
        label=label or f"{action_id}",
        source=source,
    )




def smelt(
    bundle: ActionBundle,
    ctx: CaseContext,
    *,
    item: str,
    raw: str,
    batch: float = 1.0,
    action_id: str | None = None,
    dimension: str | None = None,
) -> Action:
    """熔炼：`batch` 个原料 → `batch` 个成品。燃料折进成本。"""
    cost, notes = ctx.smelt(batch, dimension=dimension)
    bundle.assumptions.extend(notes)
    bundle.record(action_id or f"smelt:{item}", cost)
    return craft(
        bundle,
        action_id=action_id or f"smelt:{item}",
        yields={item: batch},
        inputs={raw: batch},
        cost=cost.value,
        label=f"熔炼 {batch:g} 个 {raw}",
        source="smelt",
    )




# ---------------------------------------------------------------- 能力（站点）


def capability(
    bundle: ActionBundle,
    *,
    name: str,
    cost: float,
    label: str,
    source: str,
    requires: tuple[Requirement, ...] = (),
) -> Action:
    """一个「去过就行、不用消耗」的站点或状态。"""
    return Action(
        action_id=f"travel:{name}",
        item=name,
        cost=cost,
        yields={name: 1.0},
        requires=requires,
        label=label,
        source=source,
    )




def need(item: str, qty: float = 1.0, *, once: bool = True) -> Requirement:
    return Requirement(item, qty, MODE_ONCE if once else MODE_PER_USE)
