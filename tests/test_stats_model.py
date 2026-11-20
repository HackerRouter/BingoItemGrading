"""统计行形状校验。"""

from __future__ import annotations

import pytest

from bingo_grading.stats.model import StatError, WorldStat


def base(**overrides) -> dict:
    payload = {
        "pack_version": "t",
        "scope_level": "biome",
        "dimension": "minecraft:overworld",
        "biome": "minecraft:plains",
        "stat_type": "spawn_distribution",
        "subject": "",
        "condition": "",
        "value": {"biome_weights": {"minecraft:plains": 1.0}},
        "sample_size": 4,
        "confidence": "low",
    }
    payload.update(overrides)
    return payload


def test_accepts_minimal_row() -> None:
    stat = WorldStat.from_dict(base())
    assert stat.key == ("t", "biome", "minecraft:overworld", "minecraft:plains", "spawn_distribution", "", "")


def test_rejects_unknown_field() -> None:
    with pytest.raises(StatError, match="未知字段"):
        WorldStat.from_dict(base(extra=1))


def test_rejects_unknown_value_key() -> None:
    with pytest.raises(StatError, match="未知键"):
        WorldStat.from_dict(base(value={"biome_weights": {}, "typo": 1}))


def test_rejects_missing_value_key() -> None:
    with pytest.raises(StatError, match="缺键"):
        WorldStat.from_dict(base(value={}))


def test_rejects_global_with_biome() -> None:
    with pytest.raises(StatError, match="global"):
        WorldStat.from_dict(base(scope_level="global"))


def test_rejects_biome_subject_without_subject() -> None:
    with pytest.raises(StatError, match="biome_subject"):
        WorldStat.from_dict(base(scope_level="biome_subject"))


def test_rejects_unknown_stat_type() -> None:
    with pytest.raises(StatError, match="stat_type"):
        WorldStat.from_dict(base(stat_type="ore_density_v2"))


def test_round_trip() -> None:
    stat = WorldStat.from_dict(base(parent_scope=["t", "dimension", "minecraft:overworld", "", "spawn_distribution", "", ""]))
    again = WorldStat.from_dict(stat.as_dict())
    assert again == stat
