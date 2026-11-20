"""末地/下界维度判定：结构优先于关键词。"""

from __future__ import annotations

from bingo_grading import paths
from bingo_grading.sources import routes as route_module
from bingo_grading.sources.knowledge import RouteRules

RULES = RouteRules(
    dimension_keywords=(
        ("the_nether", ("minecraft:nether_", "minecraft:blaze_")),
        ("the_end", ("minecraft:chorus_", "minecraft:shulker", "minecraft:ender_dragon")),
    ),
    structure_dimensions=(
        ("minecraft:end_city", "minecraft:the_end"),
        ("minecraft:fortress", "minecraft:the_nether"),
    ),
    underground_structure_sets=frozenset(),
)


def test_structure_dimension_beats_missing_keyword() -> None:
    """潜影贝名里看不出末地，但前置是末地城。"""
    assert (
        route_module.decide(
            source_type="mob_drop",
            subject="minecraft:shulker",
            prereq=("structure:minecraft:end_city",),
            rules=RouteRules(structure_dimensions=(("minecraft:end_city", "minecraft:the_end"),)),
        )
        == "other_dimension"
    )


def test_structure_dimension_alone_is_enough() -> None:
    """即使 subject 完全看不出维度，结构也能定。"""
    rules = RouteRules(structure_dimensions=(("minecraft:end_city", "minecraft:the_end"),))
    assert (
        route_module.decide(
            source_type="mob_drop",
            subject="minecraft:unknown_thing",
            prereq=("structure:minecraft:end_city",),
            rules=rules,
        )
        == "other_dimension"
    )


def test_dragon_keyword() -> None:
    assert (
        route_module.decide(
            source_type="mob_drop",
            subject="minecraft:ender_dragon",
            prereq=("assume:end",),
            rules=RULES,
        )
        == "other_dimension"
    )


def test_chorus_is_end() -> None:
    assert (
        route_module.decide(
            source_type="block_drop",
            subject="minecraft:chorus_plant",
            prereq=(),
            rules=RULES,
        )
        == "other_dimension"
    )


def test_ender_pearl_is_not_end() -> None:
    """末影珍珠名里有 `ender`，但它不是末地独占资源。"""
    assert (
        route_module.decide(
            source_type="mob_drop",
            subject="minecraft:enderman",
            prereq=("world:minecraft:overworld",),
            rules=RULES,
        )
        == "surface"
    )


def test_overworld_structure_stays_surface() -> None:
    assert (
        route_module.decide(
            source_type="loot_table",
            subject="minecraft:chests/village/village_temple",
            prereq=("assume:structure_loot",),
            rules=RouteRules(structure_dimensions=(("minecraft:end_city", "minecraft:the_end"),)),
        )
        == "surface"
    )


def test_structure_dimensions_loaded_from_repo() -> None:
    from pathlib import Path

    from bingo_grading.sources.knowledge import load_routes

    rules = load_routes(paths.KNOWLEDGE_ROOT / "routes.toml")
    table = dict(rules.structure_dimensions)
    assert table["minecraft:end_city"] == "minecraft:the_end"
    assert table["minecraft:fortress"] == "minecraft:the_nether"
    # 关键词表补上了以前漏的两个
    keywords = dict(rules.dimension_keywords)["the_end"]
    assert "minecraft:shulker" in keywords
    assert "minecraft:ender_dragon" in keywords
