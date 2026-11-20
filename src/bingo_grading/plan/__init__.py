"""路线竞争：把「来源」当动作，用供给曲线算平行路线。

设计见 `docs/design-route-competition.md`，本包按那里的规则落地：

- `actions`：动作（成本、产出向量、容量、前置）。
- `supply`：供给曲线（OR 合并、AND 串联、Pareto 剪枝）。
- `tiers`：分层可达性。前置必须来自**更早**的层，于是循环依赖自动不可行。
- `requires`：前置折算成钱，`once` / `per_use` 两种模式。
- `routes` / `solve`：按依赖图拓扑序求曲线，产出主路线、备选段与交叉点。

本包不做 IO，也不认识统计层：动作从哪儿来由调用方决定
（`bingo_grading.case.sources` 的动作工厂、`sources/actions/` 的自动入口）。
"""

from __future__ import annotations

from .actions import (
    MODE_ONCE,
    MODE_PER_USE,
    MODES,
    Action,
    ActionError,
    ActionSet,
    Requirement,
    is_capability,
)
from .requires import Charge, charge, dedupe_once, per_invocation_cost
from .routes import Crossover, Plan, PlanError, Step, build_plan
from .solve import Skipped, SolveError, Solved, solve
from .supply import Curve, Segment, SupplyError, merge, merge_race, prune
from .tiers import Cycle, Schedule, TierError, build_schedule

__all__ = [
    "MODE_ONCE",
    "MODE_PER_USE",
    "MODES",
    "Action",
    "ActionError",
    "ActionSet",
    "Charge",
    "Crossover",
    "Curve",
    "Cycle",
    "Plan",
    "PlanError",
    "Requirement",
    "Schedule",
    "Segment",
    "Skipped",
    "SolveError",
    "Solved",
    "Step",
    "SupplyError",
    "TierError",
    "build_plan",
    "build_schedule",
    "charge",
    "dedupe_once",
    "is_capability",
    "merge",
    "merge_race",
    "per_invocation_cost",
    "prune",
    "solve",
]
