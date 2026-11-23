"""按**预算**求曲线，再按曲线出方案。

## 为什么不能只算一次曲线

「拿到某物要多少钱」不能脱离**当时能用什么**来回答。火焰弹在「没有下界」的
时候不存在，在「已经有下界」的时候存在——同一个物品，两条成本。

## 预算

```
C[item][ℓ] = 前置链最多 ℓ 层时，拿到 item 的最小成本
             每个动作的前置按 C[·][ℓ-1] 定价
```

预算从 0 开始，每往下一步减一。于是：

- 前置链有穷，递归必然终止；
- 「点门用的火焰弹要靠进过下界」这种自指，要成立得像俄罗斯套娃一样多套一层
  `下界入口`，因而必然更贵；它不会被禁止，但永远不会赢；
- 同一条链每下一层都更严格，等于「材料来源不能比当前现状更靠后」。

## 为什么不是给物品定一个层号

一开始试过 `tier(物品) = min(产出它的动作)`，让每个动作只在自己那一层定价。
它能把循环挡住，但**过于僵硬**：一旦某物品有了一条浅来源（黑曜石能从废弃
传送门箱子里捡），所有更深的来源（岩浆浇铸）就永远进不了任何浅层动作的前置，
哪怕那条路本身完全可行。预算只限制**链条长度**，不限制「必须用最浅的那条」。

## 预算取多大

`max_level + 2`（`max_level` 是依赖分层的最大深度）。一个动作在
`自己的深度 + 1` 的预算下一定能定价，所以这个上界够用，也不随图规模爆掉。
预算是递推的层数，不是游戏阶段，报告里只看它来定位「哪一层才拿得到」。
"""

from __future__ import annotations

import heapq
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Sequence

from mcshared.scc import strongly_connected

from .actions import Action, ActionSet
from .requires import (
    Charge,
    RequirementError,
    charge_all,
    fixed_cost_of,
    per_invocation_cost,
)
from .routes import Plan, build_plan
from .supply import Curve, Segment, merge, merge_fixed, merge_race, prune
from .tiers import Schedule, build_schedule


class SolveError(ValueError):
    """求解失败（输入自相矛盾时出现）。"""


@dataclass(frozen=True)
class Skipped:
    """一个被跳过的动作，以及原因。"""

    action_id: str
    reason: str

    def as_dict(self) -> dict:
        return {"action_id": self.action_id, "reason": self.reason}


@dataclass(frozen=True)
class Solved:
    target: str
    demand: float
    schedule: Schedule
    plan: Plan
    budget: int
    curves: dict[str, Curve] = field(default_factory=dict)
    charges: dict[str, tuple[Charge, ...]] = field(default_factory=dict)
    skipped: tuple[Skipped, ...] = ()
    pruned: tuple[tuple[str, str], ...] = ()
    # 每个动作**第一次**能定价的分量序号。它把「顺序」摊开来看：
    # 序号大的分量才出现的来源，在序号小的方案里一定用不上。
    unlocks: tuple[tuple[str, int], ...] = ()

    def curve_of(self, item: str) -> Curve:
        """某物品的最终曲线。"""
        return self.curves.get(item, Curve.empty())

    def as_dict(self, *, detail: bool = True) -> dict:
        out = {
            "target": self.target,
            "demand": self.demand,
            "budget": self.budget,
            "plan": self.plan.as_dict(detail=detail),
            "schedule": self.schedule.as_dict(),
            "skipped": [item.as_dict() for item in self.skipped],
            "unlocks": {action_id: level for action_id, level in self.unlocks},
            "pruned": [
                {"action_id": action_id, "dominated_by": by}
                for action_id, by in self.pruned
            ],
        }
        if detail:
            out["curves"] = {
                item: curve.as_dict()
                for item, curve in sorted(self.curves.items())
                if curve
            }
        return out


def _curve_of(curves: dict[str, Curve], item: str) -> Curve:
    return curves.get(item, Curve.empty())


def _best_plan(
    *,
    target: str,
    demand: float,
    curve: Curve,
    actions: ActionSet,
    charges: dict[str, tuple[Charge, ...]],
    curve_of=None,
) -> Plan:
    """在「跳过前 k 段」的所有方案里取**全价**最低的一条。

    曲线单价是边际成本，不含 `once` 前置——这是有意的，否则同一趟行程里的
    每个动作都会把旅行费重叠一遍。但代价是「单价最低」不等于「总价最低」：
    走 143 格去挖一处矿便宜到每件 1.5，却可能抵不过跑一趟村庄的固定花费。
    所以这里把前 k 段逐个跳掉重算，比总价。段数很少（一般不超过十条）。
    """
    best: Plan | None = None
    for skip in range(len(curve.segments)):
        plan = build_plan(
            target=target,
            demand=demand,
            curve=curve,
            actions=actions,
            charges=charges,
            skip=skip,
            curve_of=curve_of,
        )
        if best is None or plan.cost < best.cost - 1e-9:
            best = plan
    if best is None:
        best = build_plan(
            target=target,
            demand=demand,
            curve=curve,
            actions=actions,
            charges=charges,
            curve_of=curve_of,
        )
    return best


def _apply_race(
    staged: dict[str, list[Segment]],
    action_of: dict[str, Action],
    race_of: dict[str, str],
) -> dict[str, list[Segment]]:
    """把同 `race` 组的段合成一段（速率相加）。

    合成发生在**每个物品的曲线**上，因为同一动作对不同物品的速率不同。
    同组的动作必须前置一致——否则它们的单次成本结构不同，
    速率相加会把共享的前置重复计进去。
    """
    out: dict[str, list[Segment]] = {}
    for item, segments in staged.items():
        buckets: dict[str, list[Segment]] = {}
        plain: list[Segment] = []
        for segment in segments:
            group = race_of.get(segment.action_id)
            if group is None:
                plain.append(segment)
            else:
                buckets.setdefault(group, []).append(segment)
        for group, members in buckets.items():
            if len(members) == 1:
                plain.extend(members)
                continue
            required = {
                frozenset((req.item, req.qty, req.mode) for req in action_of[
                    segment.action_id
                ].requires)
                for segment in members
            }
            if len(required) > 1:
                names = sorted(segment.action_id for segment in members)
                raise SolveError(
                    f"并行组 {group!r} 的成员前置不一致：{names}；"
                    "速率相加会把各自的前置成本重复计一次"
                )
            plain.append(merge_race(members))
        out[item] = plain
    return out


def solve(
    actionset: ActionSet,
    target: str,
    demand: float = 1.0,
    *,
    prune_dominated: bool = True,
    max_rounds: int | None = None,
) -> Solved:
    """按依赖图的拓扑序一次算完。

    ## 为什么不分层做值迭代

    早期实现是分层值迭代：每层用上一层的曲线给**所有**动作重新定价，跑
    `max_level + 2` 层，复杂度 $O(k \\cdot V)$（实测 $k \\approx 10$）。这里把物品
    依赖图缩成强连通分量，按分量拓扑序处理：DAG 上每个分量算一遍就够
    （$O(V + E)$），环内才需要迭代。

    分层版本还有两个更严重的问题，因此整个删掉了：

    - **环内能反复吃折扣**。每一轮把「上一轮的曲线」当现状，于是「块 → 物 → 块」
      这类自指路线可以一轮比一轮便宜（实测绿宝石被算成 1.00 TU，而最便宜的
      箱子里一条就要 1.51）。循环不该凭空造价值，所以拓扑 DP 只认可实现的路线，
      结果比值迭代贵，但贵的那部分是原本就不该存在的折扣。
    - **结果依赖图规模**。值迭代的层数上限是全局的，`diamond` 在第 6 层比第 2 层
      贵 4%（段数跨过枚举上限时 `_pick` 切近似分支）；同一件物品换个图规模就会变。
      拓扑 DP 的曲线只取决于依赖关系，全图与单件子图给出同一个数。

    ## 环内怎么算

    分量内用队列松弛：一个动作只在它的某个前置的物品曲线变了时重算，
    队列空了再做一次全量校验，全都不变才算到不动点。每轮全量重算的代价是
    「组大小 × 轮数」，队列版在大环上省一个数量级。

    校验不能省：`_pick` 在段数跨过枚举上限时会切近似分支，曲线不保证单调，
    只靠「变了就唤醒下游」可能停在队列空但还没到不动点的状态。

    `budget` 字段记 `max_level + 2`，不参与计算，只作依赖深度的报告值。
    """
    if demand <= 0:
        raise SolveError(f"目标数量必须为正：{demand}")

    dropped: tuple[tuple[str, str], ...] = ()
    work = actionset
    if prune_dominated:
        result = prune(actionset.actions)
        dropped = result.dropped
        if result.dropped:
            work = ActionSet(label=actionset.label, actions=result.kept)

    schedule = build_schedule(work)
    ordered = sorted(schedule.reachable_actions(), key=lambda a: a.action_id)
    action_of = {action.action_id: action for action in ordered}
    race_of = {
        action.action_id: action.race
        for action in ordered
        if action.race is not None
    }

    # 物品图：产出 → 前置。SCC 缩点后的拓扑序保证「前置所在分量先算」。
    graph: dict[str, set[str]] = {}
    producers: dict[str, list[Action]] = {}
    for action in ordered:
        for item in action.yields:
            graph.setdefault(item, set()).update(req.item for req in action.requires)
            producers.setdefault(item, []).append(action)
    component, members, order = _component_order(graph)

    # 自举约束（`Requirement.forbid_needs`）的目标物品：图里声明了几个就算几个。
    bootstrap_targets = sorted(
        {
            name
            for action in ordered
            for req in action.requires
            for name in req.forbid_needs
        }
    )
    unreachable = {
        name: unreachable_without(name, producers) for name in bootstrap_targets
    }

    curves: dict[str, Curve] = {}
    charges: dict[str, tuple[Charge, ...]] = {}
    skip_reason: dict[str, str] = {}
    unlocks: dict[str, int] = {}

    for position, cid in enumerate(order, 1):
        group: list[Action] = []
        seen: set[str] = set()
        for item in members[cid]:
            for action in producers.get(item, ()):
                if action.action_id in seen:
                    continue
                seen.add(action.action_id)
                group.append(action)
        group.sort(key=lambda a: a.action_id)
        if not group:
            continue
        # 队列驱动：一个动作只在「它的某个前置的物品曲线变了」时重算。
        # 分量内每轮全量重算的代价是「组大小 × 轮数」；队列版在大环上省掉一个
        # 数量级（子图 1632 动作：27k 次定价 → 2k 次）。
        #
        # 队列空了还要做一次**全量校验**：`_pick` 在段数跨过枚举上限时会切近似
        # 分支，曲线不保证单调，只靠「变了就唤醒下游」可能停在队列空但还没
        # 到不动点的状态。校验一轮无变化才算收敛。
        consumers: dict[str, list[Action]] = {}
        for action in group:
            for requirement in action.requires:
                consumers.setdefault(requirement.item, []).append(action)
        slots: dict[str, dict[str, Segment]] = {}

        def apply_action(action: Action) -> list[str]:
            """给一个动作定价并把段发布到本分量的曲线。返回曲线变了的物品。"""
            try:
                charged = charge_all(
                    action,
                    curve_of=lambda item: _curve_of(curves, item),
                    budget=0,
                    forbid_of=lambda req: _bootstrap_forbid(
                        req, producers, unreachable
                    ),
                )
            except RequirementError as exc:
                skip_reason[action.action_id] = str(exc)
                return []
            surcharge = per_invocation_cost(charged)
            if not math.isfinite(surcharge):
                missing = ", ".join(
                    item.item for item in charged if not math.isfinite(item.cost)
                )
                skip_reason[action.action_id] = f"前置 {missing} 拿不到足够数量"
                return []
            fixed = fixed_cost_of(charged)
            if any(not math.isfinite(amount) for _, amount in fixed):
                missing = ", ".join(
                    item.item for item in charged if not math.isfinite(item.cost)
                )
                skip_reason[action.action_id] = f"前置 {missing} 的固定成本算不出来"
                return []
            skip_reason.pop(action.action_id, None)
            charges[action.action_id] = charged
            unlocks.setdefault(action.action_id, position)
            touched: list[str] = []
            for item in action.yields:
                # 只发布到**本分量**的曲线；组外物品由它自己的分量负责。
                if component.get(item) != cid:
                    continue
                effective = action.effective_yield(item)
                if effective <= 0:
                    continue
                segment = Segment(
                    action_id=action.action_id,
                    unit_cost=(action.cost + surcharge) / effective,
                    capacity=action.capacity * effective,
                    fixed=merge_fixed(fixed, action.overhead),
                    label=action.label,
                    # 分量序号当层的替代：同价时先用依赖更浅的来源。
                    level=position,
                    # 方差只向下传「单次产出的相对波动」，不折进单价。
                    # **只有主产物能拿它**：`yield_cv` 描述的是 `action.item` 的波动，
                    # 一条动作顺带产出的其它物品（开一箱拿到五样）波动各不相同，
                    # 套用主产物那份数就是错的——那些物品的方差按「无信息」处理。
                    cv=action.yield_cv if item == action.item else 0.0,
                )
                slot = slots.setdefault(item, {})
                if slot.get(action.action_id) == segment:
                    continue
                slot[action.action_id] = segment
                merged = _apply_race({item: list(slot.values())}, action_of, race_of)
                curve = Curve.of(merged.get(item, ()))
                if curve != curves.get(item):
                    curves[item] = curve
                    touched.append(item)
            return touched

        queue: deque[Action] = deque(group)
        queued = {action.action_id for action in group}
        limit = max_rounds if max_rounds is not None else 6 * len(group) + 16
        steps = 0
        while group and steps < limit:
            if queue:
                action = queue.popleft()
                queued.discard(action.action_id)
                steps += 1
                touched = apply_action(action)
            else:
                # 全量校验：任何一处还在变就继续，全都不变才算到不动点。
                touched = []
                for action in group:
                    steps += 1
                    touched.extend(apply_action(action))
                    if steps >= limit:
                        break
                if not touched:
                    break
            for item in touched:
                for consumer in consumers.get(item, ()):
                    if consumer.action_id in queued:
                        continue
                    queued.add(consumer.action_id)
                    queue.append(consumer)

    plan = _best_plan(
        target=target,
        demand=demand,
        curve=_curve_of(curves, target),
        actions=work,
        charges=charges,
        curve_of=lambda item: _curve_of(curves, item),
    )
    return Solved(
        target=target,
        demand=demand,
        schedule=schedule,
        plan=plan,
        budget=schedule.max_level + 2,
        curves=curves,
        charges=charges,
        skipped=tuple(
            Skipped(action_id, reason)
            for action_id, reason in sorted(skip_reason.items())
        ),
        pruned=dropped,
        unlocks=tuple(sorted(unlocks.items())),
    )


def unreachable_without(
    target: str, producers: dict[str, list[Action]]
) -> frozenset[str]:
    """不用 `target` 的前提下**拿不到**的物品集合（含 `target` 自己）。

    这是 AND-OR 图上的最小可达集：一个动作能用 ⇔ 它所有前置都能用；
    一个物品能用 ⇔ 它有任一能用的动作。从空集开始往上加，加到不动点为止。
    剩下的就是「只能靠 `target` 才拿到」的东西。

    **不能只看静态依赖图**：`minecraft:iron_ingot` 的静态前置里有
    `barter:iron_ingot:piglin_bartering`（要下界），但铁锭也能挖矿，
    所以它不是「必须下界」。不动点计算会正确地把铁锭判成可达。

    用途见 `Requirement.forbid_needs`：`portal:patch_ruined` 的黑曜石不许用
    「去下界结构挖」那条来源——那要求先有门。
    """
    reachable: set[str] = set()
    changed = True
    while changed:
        changed = False
        for item, acts in producers.items():
            if item == target or item in reachable:
                continue
            for action in acts:
                if all(req.item in reachable for req in action.requires):
                    reachable.add(item)
                    changed = True
                    break
    return frozenset(producers) - reachable


def _bootstrap_forbid(
    requirement,
    producers: dict[str, list[Action]],
    unreachable: dict[str, frozenset[str]],
) -> tuple[str, ...]:
    """把 `Requirement.forbid_needs` 解成「要剔除哪些来源动作」。

    只要某个来源动作的**任一**前置落进「不用目标就拿不到」的集合，这条来源
    就不能用来满足这个前置。
    """
    targets = requirement.forbid_needs
    if not targets:
        return ()
    dead = [unreachable[name] for name in targets if name in unreachable]
    if not dead:
        return ()
    return tuple(
        action.action_id
        for action in producers.get(requirement.item, ())
        if any(req.item in blocked for req in action.requires for blocked in dead)
    )


def _component_order(
    graph: dict[str, set[str]],
) -> tuple[dict[str, int], dict[int, list[str]], list[int]]:
    """物品图 → (分量编号, 成员, 分量拓扑序)。依赖在前的顺序。

    SCC 缩点后是 DAG，用 Kahn 排序。`strongly_connected` 会给单点分量编号，
    所以不需要另外补（旧实现里 `component_members` 只返回环，那个坑已不存在）。
    """
    component = strongly_connected(graph)
    members: dict[int, list[str]] = {}
    for node, cid in component.items():
        members.setdefault(cid, []).append(node)
    for values in members.values():
        values.sort()

    depends: dict[int, set[int]] = {cid: set() for cid in members}
    for item, required in graph.items():
        cid = component[item]
        for name in required:
            other = component.get(name)
            if other is not None and other != cid:
                depends[cid].add(other)
    dependents: dict[int, set[int]] = {cid: set() for cid in members}
    for cid, parents in depends.items():
        for parent in parents:
            dependents[parent].add(cid)

    pending = {cid: set(parents) for cid, parents in depends.items()}
    ready = [cid for cid, parents in pending.items() if not parents]
    heapq.heapify(ready)
    order: list[int] = []
    while ready:
        cid = heapq.heappop(ready)
        order.append(cid)
        for child in sorted(dependents[cid]):
            pending[child].discard(cid)
            if not pending[child]:
                heapq.heappush(ready, child)
    if len(order) < len(members):
        # 缩点图不该有环；真出现说明 `strongly_connected` 与实际边不一致。
        order.extend(sorted(set(members) - set(order)))
    return component, members, order
