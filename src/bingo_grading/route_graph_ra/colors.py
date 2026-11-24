"""路线颜色：成本比 → 浓淡；最优/分叉赢家 → 红色。

从旧 `route_graph.py` 抽出的唯一实现，色表工具与新渲染器共用这一份。
"""

from __future__ import annotations

import math

from ..plan.explain import PathTree

BEST_COLOR = "#1d4e73"
WORST_COLOR = "#cbe6f0"
COST_RATIO_CAP = 4.0
HIGHLIGHT_COLOR = "#b91c1c"


def _mix(best: str, worst: str, t: float) -> str:
    """两个 `#rrggbb` 之间线性插值；`t=0` 取 best，`t=1` 取 worst。"""
    t = max(0.0, min(1.0, t))
    left = [int(best[index : index + 2], 16) for index in (1, 3, 5)]
    right = [int(worst[index : index + 2], 16) for index in (1, 3, 5)]
    mixed = [round(a + (b - a) * t) for a, b in zip(left, right)]
    return "#" + "".join(f"{value:02x}" for value in mixed)


def color_t(ratio: float, cap: float = COST_RATIO_CAP) -> float:
    """成本比 → 插值位置：1 倍为 0（最浓），`cap` 倍及以上为 1（最浅）。"""
    if ratio <= 1.0 or not math.isfinite(ratio) or cap <= 1.0:
        return 0.0
    return min(1.0, math.log(ratio) / math.log(cap))


def route_color(ratio: float, cap: float = COST_RATIO_CAP) -> str:
    return _mix(BEST_COLOR, WORST_COLOR, color_t(ratio, cap))


def route_ink(ratio: float, cap: float = COST_RATIO_CAP) -> str:
    """路线颜色：最优路线标红，其余按成本比浓淡。"""
    if ratio <= 1.0 + 1e-9:
        return HIGHLIGHT_COLOR
    return route_color(ratio, cap)


def cost_cap(trees: list[PathTree], best: float) -> float:
    """本图最差分支的成本比；所有路线同价时返回 1。"""
    if best <= 0:
        return COST_RATIO_CAP
    worst = max((tree.total_cost for tree in trees), default=best)
    return worst / best if worst > best else 1.0
