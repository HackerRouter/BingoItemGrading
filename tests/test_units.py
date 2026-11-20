"""单位、档位与分数映射。"""

from __future__ import annotations

import math

import pytest

from bingo_grading import units


def test_tier_boundaries() -> None:
    assert units.tier_of(7.0) == 1
    assert units.tier_of(69.99) == 1
    assert units.tier_of(70) == 2
    assert units.tier_of(2099.9) == 4
    assert units.tier_of(2100) == 5
    assert units.tier_of(70_000) == 5


def test_tier_representatives_match_docs() -> None:
    assert units.TIER_REPRESENTATIVE[1] == pytest.approx(22.14, abs=0.01)
    assert units.TIER_REPRESENTATIVE[2] == pytest.approx(121.24, abs=0.01)
    assert units.TIER_REPRESENTATIVE[3] == pytest.approx(383.41, abs=0.01)
    assert units.TIER_REPRESENTATIVE[4] == pytest.approx(1212.44, abs=0.01)
    assert units.TIER_REPRESENTATIVE[5] == pytest.approx(6640.78, abs=0.01)
    for index, (low, high) in enumerate(units.TIER_BOUNDS, start=1):
        assert units.TIER_REPRESENTATIVE[index] == pytest.approx(math.sqrt(low * high))


def test_score_is_monotonic_and_clamped() -> None:
    """每 1 分 = 成本 ×√2，零点在 `SCORE_FLOOR`（0.7 秒）。"""
    assert units.score_from_cost(units.SCORE_FLOOR) == 0
    # 每翻倍涨 2 分（零点 0.7 秒）
    assert units.score_from_cost(1.4) == 2
    assert units.score_from_cost(5.6) == 6
    assert units.score_from_cost(11.2) == 8
    assert units.score_from_cost(1e9) == units.SCORE_MAX
    assert units.score_from_cost(0.07) == units.SCORE_MIN, "比零点还便宜就夹到 0"
    # 单调
    scores = [units.score_from_cost(cost) for cost in (0.7, 1.4, 3.5, 14, 112, 2100)]
    assert scores == sorted(scores)
    # 粒度：0.728 秒与 2.03 秒差约 2.8 倍，必须能分开
    assert units.score_from_cost(2.03) - units.score_from_cost(0.728) >= 3


def test_probability_to_variance() -> None:
    assert units.variance_tier_for_probability(1.0) == "low"
    assert units.variance_tier_for_probability(0.5) == "low"
    assert units.variance_tier_for_probability(0.49) == "medium"
    assert units.variance_tier_for_probability(0.1) == "medium"
    assert units.variance_tier_for_probability(0.05) == "high"
    with pytest.raises(units.UnitError):
        units.variance_tier_for_probability(1.5)


def test_unknown_named_tiers_raise() -> None:
    with pytest.raises(units.UnitError):
        units.free_coverage("medium_high")
    with pytest.raises(units.UnitError):
        units.variance_penalty("none")
