"""`GraphActions`：一张自动拼出来的动作图，以及拼装过程的账。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Callable
from bingo_grading.case.sources import ActionBundle
from bingo_grading.plan import Action, ActionSet




@dataclass
class GraphActions:
    """一张自动拼出来的动作图，以及拼装过程的账。"""

    label: str
    bundle: ActionBundle
    # 参与翻译的来源记录条数。
    records: int = 0
    by_type: Counter = field(default_factory=Counter)
    # 没翻译成功的记录：`原因:标识` → 条数。空字典才算全覆盖。
    uncovered: Counter = field(default_factory=Counter)
    # 每个物品在来源索引里的记录条数。
    recorded: Counter = field(default_factory=Counter)
    # 有来源记录、但构建结束后没有任何动作产出的物品。
    no_action_items: list[str] = field(default_factory=list)
    # 前置指向一个「图上没有任何产出」的物品的动作：`物品 → 引用次数`。
    # 这类动作会被 `tiers` 判成 `no_rule` 后**静默丢弃**（工具名拼错、上游新增
    # 需求未接上），所以在构建时就显式记账，`bg index actions` 与 `bg doctor` 都读它。
    missing_prereqs: Counter = field(default_factory=Counter)
    # 结构性缺口（递归超深、配方环等），人读用。
    gaps: list[str] = field(default_factory=list)
    # 已发出的动作 ID → 它服务的物品。同一个方块会掉不同物品
    # （铁矿石 → 粗铁 / 铁矿石自己），ID 只由方块与来源拼成，撞车时必须
    # 分辨「真重复」与「两件物品共用同一段采集」——后者直接丢掉的话，
    # 先被访问到的那件物品就独占了这条来源，后访问的那件少一条路线，
    # 而访问顺序取决于 `max_depth`。
    _ids: dict[str, str] = field(default_factory=dict, repr=False)
    # 已用「跑一趟」动作覆盖的结构集合。逐表路线据此跳过，不重复计价。
    batched_structures: set[str] = field(default_factory=set, repr=False)
    # 递归访问回调。构造表要能展开自己依赖的物品，而 `_ensure_access`
    # 在 `build()` 的闭包外侧，所以构造完成后再回填。
    visit: Callable[[str, int], None] | None = field(default=None, repr=False)
    # 方块变换（`transmutes`）用到的原料/工具。它们要在主链展开完再 visit——
    # 插在 `visit()` 里展开会改变 `done` 的先后顺序，同一个物品在联合构建
    # 与单件构建下拿到不同深度，铜链因此整体漂移。
    transmute_needs: set[str] = field(default_factory=set, repr=False)
    # 一次性能力（水源之类）的登记表，由 `build()` 持有。
    once_caps: set[str] = field(default_factory=set, repr=False)

    def produced_items(self) -> set[str]:
        """图上实际出现过的物品：主产物与所有副产物。"""
        out: set[str] = set()
        for action in self.bundle.actions:
            out.add(action.item)
            out.update(action.yields)
        return out

    def settle_coverage(self) -> list[str]:
        """结算「有来源记录、但一个动作都没有」的物品。"""
        produced = self.produced_items()
        self.no_action_items = sorted(
            item for item in self.recorded if item not in produced
        )
        return self.no_action_items

    def settle_prereqs(self) -> Counter:
        """结算「前置物品在图上不存在」的动作。

        `capability:` 前缀除外：那是状态，本来就没有物品产出（缺能力由
        `uncovered` 单独记账）。这里只收真物品——出现了就是 bug（名字拼错），
        或者上游新增了某个需求而本侧还没接上。
        """
        produced = self.produced_items()
        self.missing_prereqs = Counter(
            req.item
            for action in self.bundle.actions
            for req in action.requires
            if not req.item.startswith("capability:") and req.item not in produced
        )
        return self.missing_prereqs

    def emit(self, *actions: Action | None) -> None:
        """发一个动作；同一「ID + 物品」重复就跳过并记账。

        ID 撞车但物品不同时改名保留：`mine:cave:iron_ore` 既是「粗铁」的
        来源也是「铁矿石方块」的来源，两者都要留在图上让引擎比较。
        全库联合构建时拒绝碰撞会让结果随访问顺序变化——实测同一件物品
        在 `max_depth=3` 有 17 条方块来源、`max_depth=6` 只剩 1 条。
        """
        for action in actions:
            if action is None:
                continue
            owner = self._ids.get(action.action_id)
            if owner is None:
                self._ids[action.action_id] = action.item
                self.bundle.add(action)
                continue
            if owner == action.item:
                self.gaps.append(f"动作 {action.action_id} 重复，已跳过")
                continue
            renamed = f"{action.action_id}@{action.item.split(':')[-1]}"
            if renamed in self._ids:
                self.gaps.append(f"动作 {renamed} 重复，已跳过")
                continue
            self._ids[renamed] = action.item
            self.bundle.add(replace(action, action_id=renamed))
            self.gaps.append(
                f"动作 {action.action_id} 同时服务多件物品，按物品改名为 {renamed}"
            )

    def actionset(self) -> ActionSet:
        return self.bundle.actionset()

    def summary(self) -> str:
        parts = [f"{self.records} 条来源"]
        parts.extend(f"{name}={count}" for name, count in self.by_type.most_common())
        if self.uncovered:
            parts.append(
                "未接入 "
                + "、".join(
                    f"{reason}×{count}"
                    for reason, count in self.uncovered.most_common()
                )
            )
        return "；".join(parts)
