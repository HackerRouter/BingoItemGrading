"""单位、档位与分数映射。

本文件只管**换算与评分口径**：TU 的定义、时间档位、档位系数、分数零点。
游戏数据不在这里——方块破坏与熔炼时长、移动倍率、模型规模、世界事实
全部在 `gamedata.py`（那份文件按主题分区）。
调这里的常量等于调分数表，调用方只能引用这里导出的名字。
"""

from __future__ import annotations

import math

# **1 TU = 1 秒**。TU 就是秒，不再存第二个“1 TU 等于 7 秒”的换算。
# 移动、挖掘、交互的秒数直接就是成本，日志里的 TU 数字不用心算。
#
# 档位边界与分数零点都是绝对 TU 值，改这里必须同步 ×N（否则分布整体漂移）。
SECONDS_PER_TU = 1.0

# 1 TU 对应的地表直线跑图格数 = 1 秒 × 疾跑速度。
# 实测疾跑 5.612 格/秒（`gamedata.SPRINT_BLOCKS_PER_SECOND`），所以 1 秒跑 5.612 格。
# `tests/test_gamedata.py` 钉住了这个派生关系。
#
# 原先是 100（÷7 秒 = 14.3 格/秒），比疾跑快 2.55 倍，也快过速度 II 药水。
#
# **不再加地形折减**：距离本身取的是「最近结构的直线距离」，实际要绕路、跳障碍，
# 已经偏乐观；而铺路、坐船、跑跳又比纯疾跑快。两个方向相反，取纯疾跑是中性的。
RUN_BLOCKS_PER_TU = 5.612

# 奔跑时 1 格所需的 TU（= 秒）。
TU_PER_BLOCK_RUN = 1.0 / RUN_BLOCKS_PER_TU

# 时间档位的区间边界（秒）。第一档下界 7 秒，第五档上界 21000 秒（约 5.8 小时）。
# 沿用旧口径 1 TU = 7 秒时的原值 ×7，所以档位分布不变。
TIER_BOUNDS: tuple[tuple[float, float], ...] = (
    (7.0, 70.0),
    (70.0, 210.0),
    (210.0, 700.0),
    (700.0, 2100.0),
    (2100.0, 21000.0),
)

# 档位代表值 = 档内几何中点。档位从 1 开始编号。
TIER_REPRESENTATIVE: dict[int, float] = {
    index + 1: math.sqrt(low * high)
    for index, (low, high) in enumerate(TIER_BOUNDS)
}

# `free_coverage` 三档系数。
FREE_COVERAGE: dict[str, float] = {"low": 0.2, "medium": 0.5, "high": 0.8}

# `variance_penalty` 三档系数。
VARIANCE_PENALTY: dict[str, float] = {"low": 1.0, "medium": 1.2, "high": 1.5}

# 概率 → 方差档位。按概率从高到低匹配，第一项命中即返回。
PROBABILITY_TO_VARIANCE: tuple[tuple[float, str], ...] = (
    (0.5, "low"),
    (0.1, "medium"),
    (0.0, "high"),
)

# 分数区间上下界。
#
# 以前是 0–20 且**每 1 分翻倍**，实测全库只用到 0–11 档：同是「几秒内」的
# 东西全挤在 0 档（占 36%），0.5 秒和 1.4 秒差 3 倍也分不开。直方图上看不出结构。
# 现在每 1 分 = 成本 ×√2（即「每 2 分翻倍」），同一批数据摊到 0–29 档。
SCORE_MIN = 0
SCORE_MAX = 30

# 分数的零点：`SCORE_FLOOR` 秒记 0 分。
#
# 它**不参与成本计算**，只决定 0 分档覆盖多宽。取 0.7 秒（旧口径 0.1 TU），
# 让「顺手拿」的量级落在 0 分，同时不与档位第一档下界（7 秒）挤在一起。
SCORE_FLOOR = 0.7
# 每 1 分对应几个倍频程的倒数：2.0 → 每分 ×√2。
SCORE_STEP = 2.0


class UnitError(ValueError):
    """档位名或数值不合法。"""


def tier_of(cost: float) -> int:
    """代价落在第几档。超出最后一档时返回最高档。"""
    if cost < 0:
        raise UnitError(f"代价不能为负：{cost}")
    for index, (_, high) in enumerate(TIER_BOUNDS):
        if cost < high:
            return index + 1
    return len(TIER_BOUNDS)


def tier_representative(cost: float) -> float:
    """代价所在档位的代表值。"""
    return TIER_REPRESENTATIVE[tier_of(cost)]


def free_coverage(name: str) -> float:
    try:
        return FREE_COVERAGE[name]
    except KeyError:
        raise UnitError(
            f"free_coverage 档位 {name!r} 不在三档内：{sorted(FREE_COVERAGE)}"
        ) from None


def variance_penalty(name: str) -> float:
    try:
        return VARIANCE_PENALTY[name]
    except KeyError:
        raise UnitError(
            f"variance_penalty 档位 {name!r} 不在三档内：{sorted(VARIANCE_PENALTY)}"
        ) from None


def variance_tier_for_probability(probability: float) -> str:
    """概率映射到方差档位。映射规则见 ADR 0009。"""
    if not 0.0 <= probability <= 1.0:
        raise UnitError(f"概率必须在 0–1 之间：{probability}")
    for threshold, tier in PROBABILITY_TO_VARIANCE:
        if probability >= threshold:
            return tier
    return PROBABILITY_TO_VARIANCE[-1][1]


def score_from_cost(cost: float) -> int:
    """代价（TU）→ 0–30 整数档位：每 1 分 = 成本 ×√2。

    零点在 `SCORE_FLOOR`（0.1 TU ≈ 0.5 秒）：比它更便宜的夹到 0 分，
    因为那已经是「顺手拿」的量级，再分档没有意义。
    """
    if cost <= 0:
        raise UnitError(f"代价必须为正：{cost}")
    raw = round(math.log2(cost / SCORE_FLOOR) * SCORE_STEP)
    return max(SCORE_MIN, min(SCORE_MAX, raw))


def score_bounds(score: int) -> tuple[float, float]:
    """某个分数档对应的整次成本区间 `[low, high)`。

    `score_from_cost` 的逆运算：柱子、刻度、直方图分档都靠它，避免各写一份。
    """
    low = SCORE_FLOOR * 2 ** ((score - 0.5) / SCORE_STEP)
    high = SCORE_FLOOR * 2 ** ((score + 0.5) / SCORE_STEP)
    return low, high


def score_of_cost(cost: float) -> float:
    """代价（TU）→ **连续**分值（不取整）。图上的标记线用这个定位。"""
    if cost <= 0:
        raise UnitError(f"代价必须为正：{cost}")
    return math.log2(cost / SCORE_FLOOR) * SCORE_STEP
