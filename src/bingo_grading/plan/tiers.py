"""分层可达性：前置必须来自更早的层。

## 为什么要分层

「材料来源不能比当前现状更靠后」。典型例子是下界入口：

```
去下界  ← 黑曜石 ×10 + 点燃物
点燃物  ← 打火石 或 火焰弹
火焰弹  ← 火药 + 烈焰粉 + 煤
烈焰粉  ← 烈焰棒（只有下界有）
烈焰棒  ← 杀烈焰人
烈焰人  ← 去下界        ← 回到起点
```

如果只看价格，火焰弹同时出现在「点燃物」的候选里，就可能被选来点第一座门——
而它自己要用下界的东西做。这不是数值算错，是**依赖顺序**错。

## 怎么定层

```
tier(动作) = 0                              没有前置
tier(动作) = 1 + max(tier(前置物品))        有前置
tier(物品) = min(tier(产出它的动作))
```

取**最小可导出值**（从「无前置的动作」出发反复松弛，只下调不上调）。
于是：

- 每一个有限的层号都有一条**有限长度的推导链**，链底是无前置的动作；
- 纯循环（如上面那条）永远拿不到层号 → 不可行，且能给出环的证据；
- 一个动作只允许用它**自己层之前**的物品，`1 +` 保证了这一点，
  所以「按层从前到后算成本」不会用到还没算出来的东西。

层号是**依赖深度**，不是游戏阶段。它只用来排顺序与拦截循环，
不用来对外宣称「这件物品在第几阶段」。报告里把它当诊断看。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .actions import Action, ActionSet
from mcshared.scc import component_members, strongly_connected

# 「拿不到层号」用的哨兵。用 `inf` 而不是 `None` 是为了能直接比大小。
UNREACHABLE = math.inf


class TierError(ValueError):
    """分层失败（只在内部一致性被破坏时出现）。"""


@dataclass(frozen=True)
class Cycle:
    """一条循环依赖的证据链：`item -> item -> ... -> 回到起点`。"""

    chain: tuple[str, ...]

    def __str__(self) -> str:
        return " → ".join(self.chain)

    def as_dict(self) -> dict:
        return {"chain": list(self.chain)}


# 不可达的原因分类。命名与依赖项目 `ra/solve/attribute.py` 保持一致，
# 两个项目的报告能用同一套说法对照。
NO_RULE = "no_rule"              # 缺的那个物品根本没任何动作产出
BLOCKED = "blocked"              # 有产出动作，但它们自己也拿不到
CYCLE = "cycle_no_entry"         # 卡在一个没有外部入口的环里


@dataclass(frozen=True)
class Unreachable:
    """一个拿不到层号的动作，以及原因。"""

    action_id: str
    item: str
    missing: tuple[str, ...]
    cycle: Cycle | None = None
    reason: str = BLOCKED

    def as_dict(self) -> dict:
        out = {
            "action_id": self.action_id,
            "item": self.item,
            "reason": self.reason,
            "missing": list(self.missing),
        }
        if self.cycle is not None:
            out["cycle"] = list(self.cycle.chain)
        return out


@dataclass(frozen=True)
class Schedule:
    """分层结果。`by_tier[i]` 是第 `i` 层能用的动作。"""

    item_tier: dict[str, int]
    action_tier: dict[str, int]
    by_tier: tuple[tuple[Action, ...], ...]
    unreachable: tuple[Unreachable, ...]
    cycles: tuple[Cycle, ...]

    @property
    def max_tier(self) -> int:
        return len(self.by_tier) - 1

    # 「层」与「档」是同一个东西的两种叫法：`tier` 在 `bingo_grading.units` 里已经表示
    # 「代价落第几档」，这里是依赖深度。方法名用 `level` 避免误读。
    @property
    def max_level(self) -> int:
        return self.max_tier

    def level_of_action(self, action_id: str) -> int | None:
        return self.action_tier.get(action_id)

    def tier_of(self, item: str) -> int | None:
        return self.item_tier.get(item)

    def actions_at(self, tier: int) -> tuple[Action, ...]:
        if 0 <= tier < len(self.by_tier):
            return self.by_tier[tier]
        return ()

    def reachable_actions(self) -> tuple[Action, ...]:
        return tuple(action for tier in self.by_tier for action in tier)

    def as_dict(self) -> dict:
        return {
            "items": len(self.item_tier),
            "actions": len(self.action_tier),
            "max_tier": self.max_tier,
            "unreachable": [item.as_dict() for item in self.unreachable],
            "cycles": [cycle.as_dict() for cycle in self.cycles],
            "by_tier": [
                {
                    "tier": index,
                    "actions": [action.action_id for action in actions],
                }
                for index, actions in enumerate(self.by_tier)
            ],
        }


def _tier_of_requirements(action: Action, item_tier: dict[str, int]) -> int:
    """动作的层号。前置物品层号已经全知道时才有意义。"""
    if not action.requires:
        return 0
    return 1 + max(item_tier[req.item] for req in action.requires)


def _relax(actions: tuple[Action, ...]) -> dict[str, int]:
    """从「无前置」出发反复松弛，求最小可导出层号。

    每一轮用**当前已知**的层号重算，只下调。每一轮至少让某个物品的层号
    严格变小（或新出现一个物品），层号下界是 0，所以轮数有上限。
    """
    item_tier: dict[str, int] = {}
    # 链最长不超过动作数（每跳至少多一个动作），改进波再传播一遍，取两倍余量。
    rounds = 2 * len(actions) + 2
    for _ in range(rounds):
        changed = False
        for action in actions:
            if any(req.item not in item_tier for req in action.requires):
                continue
            tier = _tier_of_requirements(action, item_tier)
            for produced in action.yields:
                current = item_tier.get(produced, UNREACHABLE)
                if tier < current:
                    item_tier[produced] = tier
                    changed = True
        if not changed:
            return item_tier
    raise TierError(
        "分层未收敛：动作数 %d，轮数用完仍有改进；"
        "这不该发生，说明层号图上出现了负向改进的循环" % len(actions)
    )


def _item_graph(actions: tuple[Action, ...]) -> dict[str, set[str]]:
    """前置 → 产出 的物品图。环就是「互相等待」的那组物品。"""
    graph: dict[str, set[str]] = {}
    for action in actions:
        for produced in action.yields:
            targets = graph.setdefault(produced, set())
            for req in action.requires:
                targets.add(req.item)
    return graph


def _dead_ring(
    item: str,
    rings: dict[int, tuple[str, ...]],
    component: dict[str, int],
    reachable: set[str],
) -> tuple[str, ...] | None:
    """`item` 是否卡在一个**没有外部入口**的环里。

    判据是分量性质，不是「某条路径走回了起点」：该分量自身成员一个都不可达，
    且分量大小 > 1。有任何一个成员能从外面拿到，这个环就不算死锁。
    """
    cid = component.get(item)
    if cid is None or cid not in rings:
        return None
    members = rings[cid]
    if any(name in reachable for name in members):
        return None
    return members


def _witness(
    start: Action,
    producers: dict[str, list[Action]],
    reachable: set[str],
    item_tier: dict[str, int],
) -> tuple[tuple[str, ...], tuple[str, ...] | None]:
    """从一个不可达动作往下走，列它卡住的物品。

    这里只负责找**断点**（走到没有生产者的物品），不负责判环——环交给
    SCC 判（见 `_dead_ring`）。以前靠「一条路径走回起点」判环，会把
    「有回路但另有入口」的情况错报成死锁。
    """
    missing: set[str] = set()
    path: list[str] = [start.item]
    action = start
    for _ in range(len(producers) + len(item_tier) + 2):
        unresolved = [req.item for req in action.requires if req.item not in item_tier]
        missing.update(req.item for req in action.requires if req.item not in reachable)
        if not unresolved:
            break
        target = unresolved[0]
        candidates = [
            candidate
            for candidate in producers.get(target, [])
            if candidate.action_id != action.action_id
        ]
        if not candidates:
            missing.add(target)
            break
        if len(path) > len(producers) * 2:
            break
        path.append(target)
        action = candidates[0]
    return tuple(sorted(missing)), None


def _canonical(chain: tuple[str, ...]) -> tuple[str, ...]:
    """把一个环旋转到字典序最小的写法。

    `a → b → a` 与 `b → a → b` 是同一个环，报告里只该出现一次。
    """
    if len(chain) < 2:
        return chain
    core = chain[:-1] if chain[0] == chain[-1] else chain
    if not core:
        return chain
    best = core
    for shift in range(1, len(core)):
        rotated = core[shift:] + core[:shift]
        if rotated < best:
            best = rotated
    return best + (best[0],)


def build_schedule(actionset: ActionSet) -> Schedule:
    """给一组动作分层。"""
    actions = actionset.actions
    item_tier = _relax(actions)

    reachable = set(item_tier)
    # 按**全部产出**建索引：副产物也算来源，否则会把「只在箱子里顺带出」的物品
    # 误报成断点。
    producers: dict[str, list[Action]] = {}
    for action in actions:
        for name in action.yields:
            producers.setdefault(name, []).append(action)

    # 环用一次 SCC 算准：分量性质（自身成员全不可达 + 大小 > 1）才是死锁判据。
    component = strongly_connected(_item_graph(actions))
    rings: dict[int, tuple[str, ...]] = {
        cid: tuple(nodes)
        for cid, nodes in component_members(component).items()
        if len(nodes) > 1
    }

    action_tier: dict[str, int] = {}
    unreachable: list[Unreachable] = []
    cycles: list[Cycle] = []
    seen_cycles: set[tuple[str, ...]] = set()

    for action in actions:
        if all(req.item in item_tier for req in action.requires):
            action_tier[action.action_id] = _tier_of_requirements(action, item_tier)
            continue
        missing, _ = _witness(action, producers, reachable, item_tier)
        ring = _dead_ring(action.item, rings, component, reachable)
        cycle = Cycle(chain=_canonical(ring + (ring[0],))) if ring else None
        if cycle is not None:
            reason = CYCLE
        elif any(name not in producers for name in missing):
            reason = NO_RULE
        else:
            reason = BLOCKED
        unreachable.append(
            Unreachable(
                action_id=action.action_id,
                item=action.item,
                missing=missing,
                cycle=cycle,
                reason=reason,
            )
        )
        if cycle is not None and cycle.chain not in seen_cycles:
            seen_cycles.add(cycle.chain)
            cycles.append(cycle)

    depth = max(action_tier.values(), default=-1) + 1
    buckets: list[list[Action]] = [[] for _ in range(depth)]
    for action in sorted(actions, key=lambda a: a.action_id):
        tier = action_tier.get(action.action_id)
        if tier is not None:
            buckets[tier].append(action)

    return Schedule(
        item_tier=item_tier,
        action_tier=action_tier,
        by_tier=tuple(tuple(bucket) for bucket in buckets),
        unreachable=tuple(unreachable),
        cycles=tuple(cycles),
    )
