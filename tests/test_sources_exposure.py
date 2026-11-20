"""路线判据：实测暴露优先于手写的地下清单。"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from bingo_grading.sources.exposure import ExposureRoutes
from bingo_grading.sources.routes import decide


@dataclass
class Row:
    """`WorldStat` 的最小替身：只需要 stat_type / subject / value。"""

    stat_type: str
    subject: str
    value: dict


def _exposure(subject: str, air: float, water: float) -> Row:
    return Row(
        stat_type="block_exposure",
        subject=subject,
        value={"air_exposed_share": air, "water_share": water},
    )


@pytest.fixture
def exposure() -> ExposureRoutes:
    return ExposureRoutes.from_rows(
        [
            _exposure("minecraft:bamboo", 0.964, 0.0),
            _exposure("minecraft:sand", 0.094, 0.422),
            _exposure("minecraft:clay", 0.063, 0.048),
            _exposure("minecraft:gravel", 0.027, 0.134),
            Row("ore_density", "minecraft:iron_ore", {"per_chunk_density": 12.0}),
        ]
    )


def test_majority_air_or_water_is_surface(exposure: ExposureRoutes) -> None:
    """多数贴空气/水就是地表：竹子 96%、沙子 9%+42%。"""
    assert exposure.route_for("minecraft:bamboo") == "surface"
    assert exposure.route_for("minecraft:sand") == "surface"


def test_buried_blocks_are_underground(exposure: ExposureRoutes) -> None:
    """粘土 11%、砾石 16% 都贴不到空气或水。"""
    assert exposure.route_for("minecraft:clay") == "underground"
    assert exposure.route_for("minecraft:gravel") == "underground"


def test_ore_blocks_are_underground_even_without_exposure(
    exposure: ExposureRoutes,
) -> None:
    """矿石按 `ore_density` 判地下——`routes.toml` 的清单漏了 iron_ore。"""
    assert exposure.route_for("minecraft:iron_ore") == "underground"


def test_unknown_block_falls_back_to_none(exposure: ExposureRoutes) -> None:
    """没有实测也没有矿石行时返回 None，由调用方退回手写清单。"""
    assert exposure.route_for("minecraft:not_a_block") is None


def test_decide_prefers_exposure_over_the_hand_written_list(
    exposure: ExposureRoutes,
) -> None:
    """`decide` 用实测暴露：`iron_ore` 不在清单里也不会被当成地表。"""
    rules = type("R", (), {})()
    # 手写清单说「不是地下」，实测说「是地下」——后者应当赢
    rules.is_underground_block = lambda subject: False  # type: ignore[attr-defined]
    rules.other_dimension_of = lambda subject: None  # type: ignore[attr-defined]
    rules.dimension_of_structures = lambda prereq: None  # type: ignore[attr-defined]
    assert (
        decide(
            source_type="block_drop",
            subject="minecraft:iron_ore",
            prereq=(),
            rules=rules,
            exposure=exposure,
        )
        == "underground"
    )
    # 没有 exposure、也没有矿石行时，退回清单的行为不变
    assert (
        decide(
            source_type="block_drop",
            subject="minecraft:mystery",
            prereq=(),
            rules=rules,
            exposure=exposure,
        )
        == "surface"
    )
