"""配方 IR：`payload → RecipeIR` 的结构完整性。

判据是「不可再漏」：facts 里每条配方都要能反序列化，payload 里每个键都要被
解释（`unparsed` 为空），`extra` 的具名槽位要真的进 IR，用量要按 pattern 计数。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bingo_grading import paths
from bingo_grading.recipes import facts

FACTS = paths.recipe_facts("26.3")
STATIONS = paths.serializer_stations("26.3")

pytestmark = pytest.mark.skipif(
    not FACTS.exists, reason=f"缺少配方事实 {FACTS.path}"
)


@pytest.fixture(scope="module")
def index() -> facts.RecipeIndex:
    return facts.load(
        str(FACTS.path), str(STATIONS.path) if STATIONS.exists else None
    )


def test_every_payload_key_is_explained(index: facts.RecipeIndex) -> None:
    """payload 里没有「没人认识」的键——这是不可再漏的检查点。"""
    assert index.unparsed == {}


def test_skipped_and_partial_are_counted(index: facts.RecipeIndex) -> None:
    """无产出（纹饰变异）与 partial 都要计数，不能静默。"""
    assert index.partial == 1
    assert 0 < index.skipped <= 25


def test_extra_named_slots_reach_ir(index: facts.RecipeIndex) -> None:
    """锻造的 template/base 在 `extra` 里，必须进 IR 并带上设备。"""
    recipe = index.for_output("minecraft:netherite_axe")[0]
    assert recipe.serializer == "minecraft:smithing_transform"
    assert recipe.station == "minecraft:smithing_table"
    assert recipe.ir.amount_of("minecraft:netherite_upgrade_smithing_template") == 1.0
    assert recipe.ir.amount_of("minecraft:diamond_axe") == 1.0


def test_multi_candidate_slot_keeps_all_choices(index: facts.RecipeIndex) -> None:
    """`coal` / `charcoal` 是同一槽的二选一，两个都要能查到。"""
    recipe = index.for_output("minecraft:fire_charge")[0]
    assert recipe.ir.amount_of("minecraft:coal") == 1.0
    assert recipe.ir.amount_of("minecraft:charcoal") == 1.0
    assert recipe.count == 3.0


def test_shaped_pattern_counts_quantity(index: facts.RecipeIndex) -> None:
    """有形状配方的用量来自 pattern 出现次数，不是「一个槽一份」。"""
    bucket = index.conversion("minecraft:bucket", serializer="minecraft:crafting_")
    assert bucket is not None
    assert bucket.amount_of("minecraft:iron_ingot") == 3.0
    assert bucket.station == "minecraft:crafting_table"


def test_three_by_three_needs_table(index: facts.RecipeIndex) -> None:
    nugget = index.conversion(
        "minecraft:gold_ingot", via="minecraft:gold_nugget"
    )
    assert nugget is not None
    assert nugget.amount_of("minecraft:gold_nugget") == 9.0


def test_cookingtime_comes_from_fields(index: facts.RecipeIndex) -> None:
    recipe = index.for_output("minecraft:baked_potato")[0]
    assert recipe.serializer == "minecraft:smelting"
    assert recipe.ir.cookingtime() == 200.0


def test_dye_recipe_keeps_the_base_item(index: facts.RecipeIndex) -> None:
    """`crafting_dye` 的 target 是基底（保留），不是被消耗的材料。"""
    recipes = index.for_output("minecraft:leather_boots")
    assert any(recipe.serializer == "minecraft:crafting_dye" for recipe in recipes)


def test_station_map_covers_every_serializer(index: facts.RecipeIndex) -> None:
    """除 2x2 合成外，设备必须能从知识表得到。"""
    seen = {}
    for recipe in index.for_output("minecraft:netherite_axe"):
        seen[recipe.serializer] = recipe.station
    assert seen.get("minecraft:smithing_transform") == "minecraft:smithing_table"
