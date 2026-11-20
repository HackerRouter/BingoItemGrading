"""树脂农场：成本口径来自游戏机制（2–3 块 / 5 秒冷却 / 瞬间挖）。"""

from __future__ import annotations

import math

import pytest

from bingo_grading import gamedata
from bingo_grading.case.context import Sourced
from bingo_grading.case.sources import ActionBundle, resin_farm, seconds


class _FakeContext:
    """只提供 `resin_farm` 需要的到达成本。"""

    def __init__(self, value: float | None = 4.5) -> None:
        self._value = value

    def pale_garden_heart_reach(self):
        if self._value is None:
            return None
        return Sourced(self._value, "probe", "probe detail"), "probe detail"


def test_resin_farm_prices_one_clump_per_trigger() -> None:
    bundle = ActionBundle(label="probe")
    action = resin_farm(
        bundle,
        _FakeContext(4.5),
        item="minecraft:resin_clump",
        action_id="harvest:resin_clump:creaking_heart",
    )
    assert action is not None
    expected = (
        gamedata.RESIN_COOLDOWN_SECONDS
        + gamedata.RESIN_HIT_SECONDS
        + gamedata.RESIN_PER_TRIGGER * gamedata.RESIN_BREAK_SECONDS
    ) / gamedata.RESIN_PER_TRIGGER
    assert action.cost == pytest.approx(seconds(expected))
    assert action.yields == {"minecraft:resin_clump": 1.0}
    assert math.isinf(action.capacity), "农场可以反复触发，次数无上限"
    # 到达苍白之园只付一次。
    assert action.overhead == (("reach:pale_garden", 4.5),)
    assert "2.5" in action.label


def test_resin_farm_absent_when_biome_data_missing() -> None:
    """没有群系数据就不造这条路线，不填默认值。"""
    bundle = ActionBundle(label="probe")
    assert (
        resin_farm(
            bundle,
            _FakeContext(None),
            item="minecraft:resin_clump",
            action_id="harvest:resin_clump:creaking_heart",
        )
        is None
    )
