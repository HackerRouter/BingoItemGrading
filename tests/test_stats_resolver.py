"""查询解析：回退链、缓存、失效。

快照来自 `tests/fixture_stats.py` 临时构造的四层占位数据，不读 `data/` ——
仓库里不放会被误当实测结果的假快照。
"""

from __future__ import annotations

import pytest

from bingo_grading.stats.index import DependencyIndex
from bingo_grading.stats.model import WorldStat
from bingo_grading.stats.resolver import StatQuery, StatResolver, require_value
from bingo_grading.stats.store import load

from . import fixture_stats

PACK = fixture_stats.PACK

BADLANDS_GOLD = ("biome_subject", "minecraft:overworld", "minecraft:badlands", "ore_exposure", "minecraft:gold_ore", "")


@pytest.fixture()
def store(tmp_path):
    return load(fixture_stats.write_snapshot(tmp_path))


def query(**overrides) -> StatQuery:
    payload = {"pack_version": PACK, "stat_type": "ore_exposure", "dimension": "minecraft:overworld"}
    payload.update(overrides)
    return StatQuery(**payload)


def test_fixture_has_expected_layers(store) -> None:
    scopes = {stat.scope_level for stat in store.rows.values()}
    assert scopes == {"global", "dimension", "biome", "biome_subject"}
    assert store.check_parents() == []


def test_hits_finest_layer(store) -> None:
    resolved = StatResolver(store).resolve(
        query(biome="minecraft:badlands", subject="minecraft:gold_ore")
    )
    assert resolved.scope_level == "biome_subject"
    assert resolved.fallback_level == 0
    assert resolved.value is not None and resolved.value["air_exposed"] == 18.5


def test_falls_back_one_layer(store) -> None:
    key = (PACK, *BADLANDS_GOLD)
    store.remove(key)
    resolved = StatResolver(store).resolve(
        query(biome="minecraft:badlands", subject="minecraft:gold_ore")
    )
    assert resolved.scope_level == "biome"
    assert resolved.fallback_level == 1
    assert resolved.value is not None and resolved.value["air_exposed"] == 14.0


def test_fallback_level_is_absolute_layer(store) -> None:
    """同一层命中必须给出同一层号，与查询带不带 subject 无关。"""
    resolver = StatResolver(store)
    with_subject = resolver.resolve(query(biome="minecraft:badlands", stat_type="biome_patch", subject=""))
    without_subject = resolver.resolve(query(biome="minecraft:badlands", stat_type="biome_patch"))
    assert with_subject.fallback_level == without_subject.fallback_level == 1
    assert with_subject.scope_level == without_subject.scope_level == "biome"


def test_falls_back_two_layers(store) -> None:
    resolved = StatResolver(store).resolve(
        query(
            biome="minecraft:windswept_hills",
            subject="minecraft:diamond_ore",
            condition="layer=underground",
        )
    )
    assert resolved.scope_level == "dimension"
    assert resolved.fallback_level == 2


def test_missing_returns_none(store) -> None:
    resolved = StatResolver(store).resolve(
        query(biome="minecraft:badlands", subject="minecraft:cow")
    )
    assert resolved.missing
    assert resolved.fallback_level is None
    assert resolved.confidence == "none"
    with pytest.raises(Exception, match="缺失"):
        require_value(resolved, consumer="测试")


def test_cache_returns_same_object(store) -> None:
    resolver = StatResolver(store)
    first = resolver.resolve(query(biome="minecraft:plains", subject="minecraft:iron_ore"))
    second = resolver.resolve(query(biome="minecraft:plains", subject="minecraft:iron_ore"))
    assert first is second


def test_edit_invalidates_cache(store) -> None:
    resolver = StatResolver(store)
    target = query(biome="minecraft:plains", subject="minecraft:iron_ore")
    before = resolver.resolve(target)
    old = before.stat
    assert old is not None and old.value["air_exposed"] == 3.4

    store.replace(
        WorldStat.from_dict({**old.as_dict(), "value": {**old.value, "air_exposed": 9.9}})
    )
    after = resolver.resolve(target)
    assert after.value is not None and after.value["air_exposed"] == 9.9


def test_dependency_index_marks_only_affected(store) -> None:
    index = DependencyIndex.for_store(store)
    index.bind("event:badlands_gold", query(biome="minecraft:badlands", subject="minecraft:gold_ore"))
    index.bind("event:plains_iron", query(biome="minecraft:plains", subject="minecraft:iron_ore"))
    index.prime()

    assert index.refresh() == set()

    key = (PACK, *BADLANDS_GOLD)
    store.remove(key)
    assert index.refresh() == {"event:badlands_gold"}
    assert index.refresh() == set()


def test_dependency_index_value_change_marks_owner(store) -> None:
    index = DependencyIndex.for_store(store)
    target = query(biome="minecraft:plains", subject="minecraft:iron_ore")
    index.bind("event:plains_iron", target)
    index.prime()

    resolved = index.resolver.resolve(target)
    old = resolved.stat
    assert old is not None
    store.replace(WorldStat.from_dict({**old.as_dict(), "sample_size": old.sample_size + 1}))
    assert index.refresh() == {"event:plains_iron"}


def test_global_change_marks_all_dependants(store) -> None:
    index = DependencyIndex.for_store(store)
    for biome in ("minecraft:badlands", "minecraft:windswept_hills", "minecraft:plains"):
        index.bind(f"event:{biome}", query(biome=biome, stat_type="biome_patch"))
    index.prime()

    global_patch = store.rows[(PACK, "global", "", "", "biome_patch", "", "")]
    store.replace(
        WorldStat.from_dict({**global_patch.as_dict(), "value": {**global_patch.value, "patch_density": 9.0}})
    )
    # 三个群系都有自身统计，global 变化不该影响它们
    assert index.refresh() == set()

    for biome in ("minecraft:badlands", "minecraft:windswept_hills", "minecraft:plains"):
        store.remove((PACK, "biome", "minecraft:overworld", biome, "biome_patch", "", ""))
    assert index.refresh() == {
        "event:minecraft:badlands",
        "event:minecraft:windswept_hills",
        "event:minecraft:plains",
    }


def test_owners_using_reports_hit_rows(store) -> None:
    index = DependencyIndex.for_store(store)
    index.bind("event:a", query(biome="minecraft:badlands", subject="minecraft:gold_ore"))
    index.prime()
    hit = (PACK, *BADLANDS_GOLD)
    assert index.owners_using(hit) == {"event:a"}


def test_fact_types_are_rejected(store) -> None:
    """命名事实没有层级回退，resolver 不接受。"""
    from bingo_grading.stats.model import StatError

    with pytest.raises(StatError):
        StatResolver(store).resolve(
            StatQuery(pack_version=PACK, stat_type="loot_expectation", subject="chests/simple_dungeon")
        )
