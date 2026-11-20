"""来源索引构建与合成展开。"""

from __future__ import annotations

from bingo_grading.recipes.expand import build_index, direct_sources, expand
from bingo_grading.sources.index import build as build_sources
from bingo_grading.sources.knowledge import Probabilities, Probability, RouteRules

from .support import redstone_graph


def routes() -> RouteRules:
    return RouteRules(
        underground_blocks=frozenset({"minecraft:redstone_ore", "minecraft:iron_ore"}),
        underground_structure_prefixes=("minecraft:chests/simple_dungeon",),
        dimension_keywords=(("the_nether", ("minecraft:chests/bastion",)),),
    )


def probabilities() -> Probabilities:
    return Probabilities(
        table={
            ("minecraft:stick", "block_drop", "minecraft:oak_leaves"): Probability(
                item="minecraft:stick",
                source_type="block_drop",
                subject="minecraft:oak_leaves",
                probability=0.05,
                basis="测试",
            )
        }
    )


def test_build_skips_recipes() -> None:
    result = build_sources(redstone_graph(), probabilities(), routes())
    redstone = [record for record in result.records if record.item == "minecraft:redstone"]
    assert {record.source_type for record in redstone} == {"block_drop", "loot_table", "trade"}
    assert not any(record.family == "recipes" for record in redstone)


def test_build_routes_and_prereq() -> None:
    result = build_sources(redstone_graph(), probabilities(), routes())
    by_subject = {record.subject: record for record in result.records if record.item == "minecraft:redstone"}

    ore = by_subject["minecraft:redstone_ore"]
    assert ore.route == "underground"
    assert set(ore.prereq) == {"tool:minecraft:iron_pickaxe", "world:minecraft:overworld"}

    dungeon = by_subject["minecraft:chests/simple_dungeon"]
    assert dungeon.route == "underground"
    assert dungeon.prereq == ("assume:structure_loot",)

    bastion = by_subject["minecraft:chests/bastion_other"]
    assert bastion.route == "other_dimension"


def test_build_applies_probability_table() -> None:
    result = build_sources(redstone_graph(), probabilities(), routes())
    stick = [record for record in result.records if record.item == "minecraft:stick"]
    assert len(stick) == 1
    assert stick[0].probabilistic
    assert stick[0].probability == 0.05


def test_craft_expands_ingredients_to_leaves() -> None:
    graph = redstone_graph()
    result = build_sources(graph, probabilities(), routes())
    direct = direct_sources(result.records)
    index = build_index(graph)

    leaves, stats = expand(index, direct, "minecraft:iron_ingot")
    assert all(leaf.source.item == leaf.item for leaf in leaves)
    assert any(leaf.item == "minecraft:iron_ore" and leaf.depth == 1 for leaf in leaves)
    assert not stats.truncated


def test_craft_rejects_salvage_cycle() -> None:
    """铁锭 → 铁粒 → 铁镐 → 木棍 这类回收链不能给铁锭贡献来源。"""
    graph = redstone_graph()
    result = build_sources(graph, probabilities(), routes())
    direct = direct_sources(result.records)
    index = build_index(graph)

    leaves, _ = expand(index, direct, "minecraft:iron_ingot")
    assert "minecraft:iron_nugget" not in {leaf.item for leaf in leaves}
    assert "minecraft:iron_pickaxe" not in {leaf.item for leaf in leaves}


def test_tag_members_expand_nested_tags() -> None:
    graph = redstone_graph()
    index = build_index(graph)
    assert index.members["tag:item/minecraft:tool_materials"] == ("minecraft:oak_planks",)


# ---------- 统计键与结构集合 ----------


def structures():
    from bingo_grading.sources.knowledge import StructureMaps

    return StructureMaps(
        loot_prefixes=(
            ("chests/village/", "minecraft:villages"),
            ("chests/ancient_city", "minecraft:ancient_cities"),
        )
    )


def test_structure_map_longest_prefix_wins() -> None:
    maps = structures()
    assert maps.set_for_table("minecraft:chests/village/village_toolsmith") == "minecraft:villages"
    assert maps.set_for_table("minecraft:chests/ancient_city_ice_box") == "minecraft:ancient_cities"
    assert maps.set_for_table("minecraft:chests/simple_dungeon") is None


def test_loot_source_stat_subject_is_structure_set() -> None:
    result = build_sources(redstone_graph(), probabilities(), routes(), structures())
    dungeon = next(record for record in result.records if record.subject == "minecraft:chests/simple_dungeon")
    assert dungeon.stat_subject is None
    assert dungeon.structure_set is None
    assert result.unmapped_struct["minecraft:chests/simple_dungeon"] == 1


def test_block_source_stat_subject_is_block() -> None:
    result = build_sources(redstone_graph(), probabilities(), routes(), structures())
    ore = next(record for record in result.records if record.subject == "minecraft:redstone_ore")
    assert ore.stat_subject == "minecraft:redstone_ore"
    assert ore.structure_set is None


def test_base_entity_strips_variant() -> None:
    from bingo_grading.sources.index import base_entity

    assert base_entity("minecraft:sheep/black") == "minecraft:sheep"
    assert base_entity("minecraft:mooshroom/brown") == "minecraft:mooshroom"
    assert base_entity("minecraft:zombie") == "minecraft:zombie"
    assert base_entity("bridge:behaviour:filled_map:0") == "bridge:behaviour:filled_map:0"


def test_underground_route_via_structure_set() -> None:
    from bingo_grading.sources import routes as route_module
    from bingo_grading.sources.knowledge import RouteRules

    rules = RouteRules(underground_structure_sets=frozenset({"minecraft:ancient_cities"}))
    assert (
        route_module.decide(
            source_type="loot_table",
            subject="minecraft:chests/ancient_city",
            prereq=(),
            rules=rules,
            structure_set="minecraft:ancient_cities",
        )
        == "underground"
    )
