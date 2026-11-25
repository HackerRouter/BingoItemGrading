"""Bingo 难度参考：把一批物品折算成同一张难度表。

## 为什么需要这一层

`bg plan` 一次回答「这一件要多久」。Bingo 的用法是反过来的：
一张卡有几十件物品，需要的是**横向可比的难度表**，以及「哪些数字不可信」。

所以这里只做三件事，不引入任何新的成本口径：

1. 对每个物品跑一遍既有的自动拼图与求解，取 `plan.cost` → `score`；
2. 把「这条分数有多可信」显式写出来（缺口、来源条数、曲线段数）；
3. 汇总成一张卡的总难度。

评分口径不在这里定义，沿用 `bingo_grading.units.score_from_cost`
（`score = clamp(round(log2(cost / SCORE_FLOOR) × SCORE_STEP), 0, 30)`，
每 1 分 = 成本 ×√2，零点 0.1 TU）。

## 置信度是怎么判的

不看「整张图报了多少缺口」，而看两件事，都能从数据自证：

1. **目标自身的来源有没有断**。`uncovered` 是整个动作用图的缺口，里面混着
   大量与目标无关的条目——查钻石时递归碰到的 `iron_block` 没有密度，
   也会计一笔。用总数判置信度就永远是 `low`，这个字段也就没用了。
   所以只数 `原因:对象` 里**对象等于目标物品**的那些。
2. **供给曲线有几段**。只有一段意味着「只有一条路」，那条路错了整件就错。

这不是统计置信度，是**模型自评的可信度**。
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass
from pathlib import Path

from bingo_grading import units
from bingo_grading.plan.actions import MODE_PER_USE

# `uncovered` 里这些不算缺口：路线另有来源，只是本条记录没接上。
#
# - `缺方块密度（有合成替代）`：铁块/金块这类 9 合 1 的方块，合成路线已经在图上；
# - `模板物品绑定（R4，无表名）`：上游只说了「模板里某容器装着它」，
#   没有战利品表名，属于模板解析的范畴。
HARMLESS_PREFIXES = (
    "缺方块密度（有合成替代）",
    "模板物品绑定（R4，无表名）",
)

# 单条来源就该被警告：一条路错了，这件物品的分数就整体错。
LOW_SEGMENT_COUNT = 1
# 段数到多少算「来源够多」。三档以内说明选择余地很窄。
NARROW_SEGMENT_COUNT = 3
# 清单超过这个件数就改用整图求解：单件走目标子图约 1.5 秒，整图一次约 6 秒。
JOINT_THRESHOLD = 4
# 不可分割的行动单元：一次调用就是一次真实的行动，不能按 0.3 次计价。
#
# 这些动作的产出是「跑一趟/触发一次之后手上有什么」，玩家没法只做 30%。
# `craft:` / `smelt:` / `mine:` 不在此列——它们可以按件线性拆分
# （拆一块铁拿 1 个锭，不必按「一次拆出 9 个」的全价算）。
ATOMIC_PREFIXES = (
    "loot:",
    "travel:",
    "spawner:",
    "haunt:",
    "raid:",
    "fish:",
    "barter:",
    "gift:",
    "bonus:",
    "cat_gift:",
    "brush:",
    "end:",
    "portal:",
    "cast:",
    "igniter:",
    "train:",
    "scoop:",
    "wither:",
    "roam:",
    # 剪一次毛必给 2 个（`loot_expectation` 按 `shear` 触发器存的期望），
    # 所以「要 1 个羊毛」也得剪一次整的，不存在剪半只羊。
    "shear:",
)

# 尾部成本的分位系数：正态单侧 95%。与 `plan.supply.Curve.tail_cost` 的默认值
# 同一个口径，改的时候两处一起改（那里是批量曲线，这里是整次调用）。
TAIL_Z = 1.645


def best_whole_cost(
    actionset,
    curves,
    item: str,
    demand: float,
    *,
    seen: frozenset[str] = frozenset(),
    memo: dict | None = None,
    actions_by_id: dict | None = None,
) -> tuple[float | None, str, str, float]:
    """按**整次调用**口径，递归取「凑够 `demand` 件」最便宜的方案。

    为什么不能直接用 `plan.cost`：引擎的曲线是连续松弛（可以调用 0.3 次），
    那是为批量规划设计的。拿 1 颗钻石会被算成「调用 0.0023 次」，摊出 0.9 TU；
    拿 1 个绿宝石的「最优方案」也会变成跑一趟试炼大厅，而实际村庄交易便宜
    两个数量级。

    **递归是关键。** 只对目标层取整会漏掉原料层：`钻石 ← 钻石块` 这条动作
    本身只要 2 秒手工，但「买 4 个钻石块」同样是整次的事——把它按均摊价算，
    就会得出「4 次拆块 34.75 TU 比跑一趟 46.37 便宜」的假结论。所以这里对每个
    动作的 `once` / `per_use` 前置都递归求整次成本，而不是沿用曲线上的单价。

        calls = ceil(demand / 一次调用产出)            # 不可分割的动作至少 1 次
        total = 动作自带固定成本 + 动作自身时间 × calls
              + Σ once 前置的整次成本                   # 只付一次
              + Σ per_use 前置的整次成本(qty × calls)   # 跟着调用次数走

    `demand` 不必为 1：Bingo 的「32 个煤炭」就传 32。均摊与整次的差别随调用
    次数收敛（差一个 `1 - 1/calls` 量级），但整次仍然更准——余数不能白拿。

    `curves` 是全部物品的供给曲线（`solved.curves`）。`seen` 防环：
    递归回到当前链路已经出现过的物品时，该分支判为不可行。

    返回 `(成本, 动作 id, 说明, 成本方差)`；没有可用方案时成本为 `None`。

    方差与成本**同步累加**，所以时两者同口径（都是整次调用），可以直接想
    `p95 = cost + z·sd`。方差只来自「单次产出的件数波动」：

        Var = Σ calls·(单次成本·产出 cv)²           # 本动作
            + Σ 前置方案的方差                     # 递归（once 只算一次）

    固成本（`overhead`）与未标 `yield_cv` 的动作当作确定量，方差贡献为 0。

    **已知局限**：候选段来自引擎按均摊口径做的 Pareto 剪枝，所以被剪掉、
    但在整次口径下更便宜的来源不参与比较。结果偏保守（高估）。

    `actions_by_id` / `memo` 可以由调用方传共享的那一份：全库计算时 1414 件
    共享同一批前置（木棍、铁锰…），不共享的话每次调用都要重建 4481 条的
    `action_id` 索引、重复算同一个前置。共享后 `memo` 只存非 `None` 的结果，
    所以不会把「撞环失败」串到别的链路上（见下面不缓存 `None` 的理由）。
    代价是：某个物品在宽松 `seen` 下算出的价会被严格 `seen` 的链路复用，
    对环上的物品偏乐观——但环本身是病态数据，`None` 不缓存已经挡住了大多数。
    """
    if memo is None:
        memo = {}
    key = (item, round(demand, 6))
    if key in memo:
        return memo[key]
    if item in seen:
        # 回到当前链路已经走过的物品：这条分支是环，无法给出有限成本。
        return (None, "", "", 0.0)
    best: float | None = None
    best_var = 0.0
    best_action = ""
    best_label = ""
    curve = curves.get(item)
    by_id = (
        actions_by_id
        if actions_by_id is not None
        else {action.action_id: action for action in actionset.actions}
    )
    for segment in curve.segments if curve else ():
        if segment.members:
            # 并行合成的段：产出无法归到单个动作上，退回线性计价。
            # cv 已在 `merge_race` 里按速率合成过，直接用段的自己的。
            total = segment.fixed_cost + segment.unit_cost * demand
            spread = demand * (segment.unit_cost * segment.cv) ** 2
            if best is None or total < best:
                best, best_var, best_action, best_label = (
                    total,
                    spread,
                    segment.action_id,
                    segment.label,
                )
            continue
        action = by_id.get(segment.action_id)
        if action is None:
            continue
        effective = action.effective_yield(item)
        if effective <= 0:
            continue
        if segment.action_id.startswith(ATOMIC_PREFIXES):
            # 不可分割：至少跑一趟，余数补齐到整次。
            calls = 1.0 if demand <= effective else float(
                math.ceil(demand / effective - 1e-9)
            )
        else:
            calls = demand / effective
        total = sum(amount for _, amount in action.overhead) + action.cost * calls
        # 方差按**每件成本**换算：`cv` 描述的是「每件成本的相对波动」，已经含了
        # 1/μ 的折减（`cv = (s/μ)·√μ`）。所以：
        #
        #     Var(n 件) = n · (单次成本 · cv / 单次产出)²
        #
        # 不能写成 `calls · (cost · cv)²`：`calls` 是**整次口径取整后**的次数，
        # 而 `cv` 是按连续松弛定的，两者一乘就把「一趟村庄给 22 个金粒」的方差
        # 放大 μ² 倍（实测 p95 从 1.17 倍虚到 7 倍）。
        #
        # 只取主产物的 `yield_cv`：一条动作顺带产出的其它物品（开一箱拿到五样）
        # 波动各不相同，套主产物那份数会把它们算成 sd 比均值还大。
        cv = action.yield_cv if item == action.item else 0.0
        spread = demand * (action.cost * cv / effective) ** 2
        for requirement in action.requires:
            need = requirement.qty * calls if requirement.mode == MODE_PER_USE else (
                requirement.qty
            )
            sub, _, _, sub_var = best_whole_cost(
                actionset,
                curves,
                requirement.item,
                need,
                seen=seen | {item},
                memo=memo,
                actions_by_id=by_id,
            )
            if sub is None:
                total = None
                break
            total += sub
            # 前置的波动也会传下来（独立随机变量，方差可加）。
            spread += sub_var
        if total is None:
            continue
        if best is None or total < best:
            best, best_var, best_action, best_label = (
                total,
                spread,
                segment.action_id,
                segment.label,
            )
    if best is None:
        # **不能缓存 None**：它往往是「递归撞上 `seen` 里的物品、这条分支被判成环」
        # 的产物，只对当前这条链路成立。缓存后别的调用会命中它，把本来走得通的
        # 路线误判为不可行——实测凋灵之星的整次成本就是这么变成 `None` 的：
        # 先算灵魂沙时缓存了某个「带自己 seen」的失败，再算凋灵骷髅就复用了它。
        return (None, "", "", 0.0)
    memo[key] = (best, best_action, best_label, best_var)
    return memo[key]


def whole_cost_of_plan(steps, once_cost: float) -> float | None:
    """按**整次调用**重算一条**已定方案**的总成本。

    与 `best_whole_cost` 的分工：那个在多个来源之间挑最便宜的，
    这个只把一条现成的方案（`plan.steps`）换算成整次口径，用于核对
    「引擎选出的方案在离散世界里的真实代价」。
    """
    total = once_cost
    for step in steps:
        invocations = float(getattr(step, "invocations", 0.0) or 0.0)
        if invocations <= 0:
            continue
        action_id = str(getattr(step, "action_id", ""))
        if not action_id.startswith(ATOMIC_PREFIXES):
            # 可分动作：线性计价，不做取整。
            total += float(getattr(step, "local_cost", 0.0)) + float(
                getattr(step, "per_use_cost", 0.0)
            )
            continue
        whole = math.ceil(invocations - 1e-9)
        if whole <= 0:
            continue
        step_cost = float(getattr(step, "local_cost", 0.0)) + float(
            getattr(step, "per_use_cost", 0.0)
        )
        total += step_cost * whole / invocations
    return total if math.isfinite(total) and total > 0 else None


@dataclass(frozen=True)
class BundleStep:
    """组合方案里的一步：某个动作调用几次、顺带解决了哪几件目标。"""

    action_id: str
    calls: float
    covers: tuple[str, ...]
    cost: float


@dataclass(frozen=True)
class Bundle:
    """一次买齐多件物品的方案。"""

    cost: float | None
    steps: tuple[BundleStep, ...]

    @property
    def feasible(self) -> bool:
        return self.cost is not None

    def as_dict(self) -> dict:
        return {
            "cost_tu": None if self.cost is None else round(self.cost, 4),
            "steps": [
                {
                    "action_id": step.action_id,
                    "calls": step.calls,
                    "covers": list(step.covers),
                    "cost_tu": round(step.cost, 4),
                }
                for step in self.steps
            ],
        }


def best_bundle(
    actionset,
    curves,
    demands: dict[str, float],
    *,
    seen: frozenset[str] = frozenset(),
    memo: dict | None = None,
    paid: frozenset[str] = frozenset(),
    top: bool = True,
) -> Bundle:
    """**一次买齐** `demands` 里所有物品的最便宜方案。

    与 `best_whole_cost()` 的区别：那个一次只问一件，几件加在一起会重复付行程，
    而且会把「同一趟顺手拿到的东西」算成各自跑一趟。实测 `loot:buried_treasures`
    一趟同时给钻石 0.96、金锭 4.48、铁锭 8.95、绿宝石 3.86……所以
    「钻石 + 金锭 + 铁锭」这三格跑一趟就够，分别算会高估两三倍。

    算法：枚举「这一趟由哪个动作负责」——一个动作能同时供给它 `yields` 里的
    所有目标，调用次数取 `max(⌈需求ᵢ ÷ 单次产出ᵢ⌉)`（跑一趟就够所有物品，
    不必各跑一次），剩下的目标递归求。这是**集合覆盖**的贪心版：
    目标件数少（Bingo 一格 1–3 件）时递归深度很浅，穷举得起。

    容量有限的动作用 `capacity` 卡住：一趟给不够的目标不会被这条动作认领。

    `paid` 是**已经付过的一次性状态**（`capability:*`）：两个目标都要「进末地」
    或「打完一场龙」时只收一次。这是跨动作的共享——`yields` 只覆盖「一个动作
    同时产出多件」，覆盖不到「两条链共用同一个上游状态」。

    `top` 控制 `paid` 只**在顶层扩展一层**：把 paid 每层都往下扩会让缓存按
    「已付集合」分片，真实图上组合数爆炸（实测 `pytest` 从 30 s 涨到跑不完）。
    顶层一层已经覆盖「同一行 Bingo 里两件都要打龙」这个诉求。
    """
    if memo is None:
        memo = {}
    key = (
        tuple(sorted((item, round(amount, 6)) for item, amount in demands.items())),
        tuple(sorted(paid)),
    )
    if key in memo:
        return memo[key]
    remaining = {item: amount for item, amount in demands.items() if amount > 0}
    if not remaining:
        empty = Bundle(0.0, ())
        memo[key] = empty
        return empty
    best: Bundle | None = None
    for action in actionset.actions:
        covered: list[str] = []
        calls = 0.0
        for item, amount in remaining.items():
            effective = action.effective_yield(item)
            if effective <= 0:
                continue
            # 产量上限不够一件都凑不齐的，这条动作认领不了。
            if math.isfinite(action.capacity) and action.capacity * effective < amount:
                continue
            need = amount / effective
            if action.action_id.startswith(ATOMIC_PREFIXES):
                need = math.ceil(need - 1e-9)
            else:
                need = max(need, 1e-9)
            covered.append(item)
            calls = max(calls, need)
        if not covered or calls <= 0:
            continue
        if action.action_id in seen:
            # 回到已经用过的动作：这条分支会原地打转。
            continue
        total = sum(amount for _, amount in action.overhead) + action.cost * calls
        # 本条动作付过的状态要累计下来，同一分支的后续目标（`tail`）才不会再付一次。
        spent = paid
        for requirement in action.requires:
            once = requirement.mode != MODE_PER_USE
            if once and requirement.item in spent:
                # 同一场龙战 / 同一趟末地：别的分支已经付过。
                continue
            if once and top:
                spent = spent | {requirement.item}
            need = requirement.qty * calls if not once else requirement.qty
            sub = best_bundle(
                actionset,
                curves,
                {requirement.item: need},
                seen=seen | {action.action_id},
                memo=memo,
                paid=spent,
                top=False,
            )
            if sub.cost is None:
                total = None
                break
            total += sub.cost
        if total is None:
            continue
        rest = {item: amount for item, amount in remaining.items() if item not in covered}
        step = BundleStep(
            action_id=action.action_id,
            calls=calls,
            covers=tuple(sorted(covered)),
            cost=sum(amount for _, amount in action.overhead) + action.cost * calls,
        )
        steps = (step,)
        if rest:
            tail = best_bundle(
                actionset,
                curves,
                rest,
                seen=seen | {action.action_id},
                memo=memo,
                paid=spent,
                top=False,
            )
            if tail.cost is None:
                continue
            total += tail.cost
            steps += tail.steps
        if best is None or total < best.cost:
            best = Bundle(total, steps)
    memo[key] = best or Bundle(None, ())
    return memo[key]


@dataclass(frozen=True)
class DifficultyRow:
    """一件物品的难度评分，以及这个评分的可信度。"""

    item: str
    # 最终分数：`max(成本分, 尾部分)`。两个维度并列输出，不合并成一个连续值。
    score: int | None
    tier: int | None
    cost_tu: float | None
    whole_cost_tu: float | None
    route: str
    route_label: str
    sources: int
    uncovered_total: int
    uncovered_own: int
    segments: int
    confidence: str
    # 尾部口径：`whole_cost_tu + TAIL_Z · sd`。`None` = 拿不到方差（所有来源都
    # 没标 `yield_cv`）或不可行；与 `whole_cost_tu` 同口径，两者可直接比。
    p95_cost_tu: float | None = None
    # 两个维度的分数：`cost_score` 只看平均成本，`tail_score` 只看 p95。
    # `score` 取两者最大值；这里留存原始值，否则看不出分数是被尾部抬上去的。
    cost_score: int | None = None
    tail_score: int | None = None
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "item": self.item,
            "score": self.score,
            "tier": self.tier,
            # 引擎口径（连续松弛）：批量看用这个。
            "cost_tu": None if self.cost_tu is None else round(self.cost_tu, 4),
            # 难度口径（整次调用）：`score` 就建在它上面。
            "whole_cost_tu": (
                None if self.whole_cost_tu is None else round(self.whole_cost_tu, 4)
            ),
            "route": self.route,
            "route_label": self.route_label,
            "sources": self.sources,
            "uncovered_total": self.uncovered_total,
            "uncovered_own": self.uncovered_own,
            "segments": self.segments,
            "confidence": self.confidence,
            "p95_cost_tu": (
                None if self.p95_cost_tu is None else round(self.p95_cost_tu, 4)
            ),
            "cost_score": self.cost_score,
            "tail_score": self.tail_score,
            "notes": list(self.notes),
        }


def own_gaps(item: str, uncovered: dict[str, int]) -> int:
    """只数**目标物品自己**的缺口。

    键的格式约定（2026-11-22 统一）：

    | 形态 | 含义 | 计入本函数 |
    |---|---|---|
    | `原因:item` | 物品级缺口，`item` 就是缺的那件 | ✅ |
    | `原因(subject):item` | 物品级缺口，括号里是主体（结构/生物/表） | ✅ |
    | `原因:subject` | **结构级**缺口，影响一整类物品，不归到某一件 | ❌ |

    `partition(":")` 只切第一个冒号，所以前两种取到的正好是 `item`
    （`item` 自己带冒号无妨）。**括号里的主体必须是短名、不能含冒号**——
    写成 `[minecraft:cow]` 会把第一个冒号切在括号里，取到的就不是物品名了。

    结构级的例子：`缺结构密度:minecraft:ancient_city`——那是「古代城市缺密度数据」，
    会让该结构下的所有物品都少一条来源，记到某一物品头上反而是错的。
    """
    total = 0
    for reason, count in uncovered.items():
        _, _, subject = reason.partition(":")
        if subject == item:
            total += count
    return total


def real_gaps(uncovered: dict[str, int]) -> int:
    """扣掉无害类别之后的缺口条数（仅作信息展示，不参与置信度）。"""
    return sum(
        count
        for reason, count in uncovered.items()
        if not reason.startswith(HARMLESS_PREFIXES)
    )


def confidence_of(*, feasible: bool, uncovered_own: int, segments: int) -> str:
    """模型自评的可信度：`none` / `low` / `medium` / `high`。

    `none` 表示连可行路线都没有——那不是「简单」或「很难」，
    是「这件物品现在算不出来」，必须与低分区分开。
    """
    if not feasible:
        return "none"
    if uncovered_own > 0 or segments <= LOW_SEGMENT_COUNT:
        return "low"
    if segments <= NARROW_SEGMENT_COUNT:
        return "medium"
    return "high"


def row_of(
    *,
    item: str,
    cost: float | None,
    whole_cost: float | None,
    feasible: bool,
    route: str,
    route_label: str,
    sources: int,
    uncovered: dict[str, int],
    segments: int,
    demand: float = 1.0,
    variance: float = 0.0,
) -> DifficultyRow:
    """把一次求解结果整理成一行难度。

    `score` 用 `whole_cost`（整次调用）而不是引擎的 `cost`（连续松弛）：
    难度问的是「凑够 `demand` 件要多久」。`demand = 1` 时两者差别最大，
    `demand` 很大时向均摊收敛（差一个 `1 - 1/calls` 量级）。

    `variance` 是同一个方案的**成本方差**（由 `best_whole_cost` 同步累加）。
    它只用来算并列的 `p95_cost_tu` 与 `tail_score`，不影响两个维度各自的定义：
    `cost_score` 只看均值、`tail_score` 只看 p95，最终 `score = max(两者)`。
    """
    own = own_gaps(item, uncovered)
    notes: list[str] = []
    p95: float | None = None
    cost_score: int | None = None
    tail_score: int | None = None
    if not feasible or whole_cost is None:
        notes.append("算不出可行路线：来源全部缺失或前置不可达")
    else:
        cost_score = units.score_from_cost(whole_cost)
        # 正态单侧 95%；没有方差信息时退化成均值本身。
        p95 = whole_cost + TAIL_Z * math.sqrt(max(0.0, variance))
        tail_score = units.score_from_cost(p95)
        if cost_score >= units.SCORE_MAX:
            notes.append("分数已封顶，实际可能更难")
        elif tail_score > cost_score:
            notes.append(
                f"分数按尾部计：均摊 {whole_cost:.2f} TU → p95 {p95:.2f} TU"
            )
        if segments <= LOW_SEGMENT_COUNT:
            notes.append("只有一条来源，该来源一旦有误整件都会错")
        if cost is not None and whole_cost > cost * 1.5:
            notes.append(
                f"要凑够 {demand:g} 件得跑整趟（均摊 {cost:.2f} TU，实际 {whole_cost:.2f} TU）"
            )
    if own:
        notes.append(f"该物品自己还有 {own} 条来源没接进模型")
    final_score = (
        None
        if cost_score is None
        else max(cost_score, cost_score if tail_score is None else tail_score)
    )
    # `tier` 跟分数同源：分数是按哪个成本抬上去的，档位就按哪个成本算。
    # 两个刻度不同（`TIER_BOUNDS` vs `SCORE_FLOOR/STEP`），不能各自取 max 混搭。
    tier_cost = whole_cost
    if tail_score is not None and cost_score is not None and tail_score > cost_score:
        tier_cost = p95
    return DifficultyRow(
        item=item,
        score=final_score,
        tier=None if tier_cost is None else units.tier_of(tier_cost),
        cost_tu=None if not feasible or cost is None else cost,
        whole_cost_tu=None if not feasible or whole_cost is None else whole_cost,
        route=route,
        route_label=route_label,
        sources=sources,
        uncovered_total=sum(uncovered.values()),
        uncovered_own=own,
        segments=segments,
        confidence=confidence_of(
            feasible=feasible, uncovered_own=own, segments=segments
        ),
        p95_cost_tu=p95,
        cost_score=cost_score,
        tail_score=tail_score,
        notes=tuple(notes),
    )


def summarize(rows: list[DifficultyRow]) -> dict:
    """一张卡的难度汇总。

    `total_score` 是各行分数之和，用来看卡的**总体量**；同时给出 `hardest`，
    因为 Bingo 的节奏通常由最难那件决定。两者并列，不合并成一个数。
    """
    scored = [row for row in rows if row.score is not None]
    hardest = max(scored, key=lambda row: row.score or 0) if scored else None
    unknown = [row.item for row in rows if row.score is None]
    shaky = [row.item for row in rows if row.confidence in ("low", "none")]
    return {
        "items": len(rows),
        "scored": len(scored),
        "total_score": sum(row.score or 0 for row in scored),
        "hardest": None
        if hardest is None
        else {
            "item": hardest.item,
            "score": hardest.score,
            "whole_cost_tu": round(hardest.whole_cost_tu or 0.0, 4),
        },
        "unknown": unknown,
        "low_confidence": shaky,
    }


def render_table(rows: list[DifficultyRow]) -> str:
    """对齐的文本表。列宽按内容算，不手抄空格数。"""
    header = (
        "物品",
        "分数",
        "档",
        "整次 TU",
        "尾部 TU",
        "均摊 TU",
        "可信度",
        "主要路线",
    )
    body = [
        (
            row.item,
            "-" if row.score is None else str(row.score),
            "-" if row.tier is None else str(row.tier),
            "-" if row.whole_cost_tu is None else f"{row.whole_cost_tu:.2f}",
            "-" if row.p95_cost_tu is None else f"{row.p95_cost_tu:.2f}",
            "-" if row.cost_tu is None else f"{row.cost_tu:.2f}",
            row.confidence,
            row.route,
        )
        for row in rows
    ]
    widths = [
        max(_display_width(line[index]) for line in [header, *body])
        for index in range(len(header))
    ]
    lines = []
    for line in [header, *body]:
        cells = []
        for index, cell in enumerate(line):
            pad = widths[index] - _display_width(cell)
            cells.append(cell + " " * pad)
        lines.append("  ".join(cells).rstrip())
    lines.insert(1, "  ".join("-" * width for width in widths))
    return "\n".join(lines)


def render_markdown(rows: list[DifficultyRow]) -> str:
    """给人看的 Markdown 表：多一列「说明」，路线 id 之外能看到在干什么。

    全库 1414 行在编辑器里可以直接预览或排序，比对齐文本表好用。
    `route_label` 里的配方路径很长，截在第一个「（」之前。
    """
    lines = [
        "| 物品 | 分数 | 档 | 整次 TU | 尾部 TU | 均摊 TU | 可信度 | 主要路线 | 说明 |",
        "|---|---:|---:|---:|---:|---:|---|---|---|",
    ]
    for row in rows:
        # 去掉「（…参数…）」尾巴，并把多余空白压成一个空格。
        label = " ".join(row.route_label.split("（", 1)[0].split())
        lines.append(
            "| "
            + " | ".join(
                (
                    row.item,
                    "-" if row.score is None else str(row.score),
                    "-" if row.tier is None else str(row.tier),
                    "-" if row.whole_cost_tu is None else f"{row.whole_cost_tu:.2f}",
                    "-" if row.p95_cost_tu is None else f"{row.p95_cost_tu:.2f}",
                    "-" if row.cost_tu is None else f"{row.cost_tu:.2f}",
                    row.confidence,
                    f"`{row.route}`" if row.route else "-",
                    label.replace("|", "\\|") or "-",
                )
            )
            + " |"
        )
    return "\n".join(lines)


def render_csv(rows: list[DifficultyRow]) -> str:
    """CSV 文本（**不含** BOM）：给表格软件用的原始数值。

    BOM 由写入端按后缀加（见 `render_table_file`），这样这里返回的仍是普通
    字符串，内联输出与测试都不用处理前导 `\ufeff`。
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        (
            "item",
            "score",
            "cost_score",
            "tier",
            "whole_cost_tu",
            "p95_cost_tu",
            "tail_score",
            "cost_tu",
            "confidence",
            "route",
            "route_label",
            "uncovered_own",
            "uncovered_total",
            "notes",
        )
    )
    for row in rows:
        writer.writerow(
            (
                row.item,
                "" if row.score is None else row.score,
                "" if row.cost_score is None else row.cost_score,
                "" if row.tier is None else row.tier,
                "" if row.whole_cost_tu is None else round(row.whole_cost_tu, 4),
                "" if row.p95_cost_tu is None else round(row.p95_cost_tu, 4),
                "" if row.tail_score is None else row.tail_score,
                "" if row.cost_tu is None else round(row.cost_tu, 4),
                row.confidence,
                row.route,
                row.route_label,
                row.uncovered_own,
                row.uncovered_total,
                "；".join(row.notes),
            )
        )
    return buffer.getvalue()


def render_table_file(rows: list[DifficultyRow], path: str) -> str:
    """按后缀选格式写表格，返回实际格式名。

    `.md` / `.markdown` → Markdown，`.csv` → CSV，其余 → 对齐文本表。

    CSV 额外写 **UTF-8 BOM**：Excel 双击打开时靠它认编码，没有 BOM 就把中文
    列（路线、说明）显示成乱码。Markdown 不写——BOM 会让 diff 首行出现隐形字符。
    """
    suffix = Path(path).suffix.lower()
    if suffix in (".md", ".markdown"):
        text, kind = render_markdown(rows), "markdown"
    elif suffix == ".csv":
        text, kind = render_csv(rows), "csv"
    else:
        text, kind = render_table(rows), "text"
    target = Path(path)
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        text + "\n", encoding="utf-8-sig" if kind == "csv" else "utf-8"
    )
    return kind


def _display_width(text: str) -> int:
    """终端显示宽度：CJK 与全角标点占两列。"""
    width = 0
    for char in text:
        width += 2 if _is_wide(char) else 1
    return width


def _is_wide(char: str) -> bool:
    code = ord(char)
    return (
        0x1100 <= code <= 0x115F
        or 0x2E80 <= code <= 0xA4CF
        or 0xAC00 <= code <= 0xD7A3
        or 0xF900 <= code <= 0xFAFF
        or 0xFE30 <= code <= 0xFE6F
        or 0xFF00 <= code <= 0xFF60
        or 0xFFE0 <= code <= 0xFFE6
    )
