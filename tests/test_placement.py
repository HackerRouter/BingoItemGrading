"""方块放置事实：只有模板来源的方块应按结构判路线。"""

from __future__ import annotations

from bingo_grading.sources import routes as route_module
from bingo_grading.sources.knowledge import RouteRules, StructureMaps
from bingo_grading.sources.placement import PlacementIndex

from .support import graph_of, rule

MAPS = StructureMaps(
    loot_prefixes=(),
    template_prefixes=(
        ("ancient_city/", "minecraft:ancient_cities"),
        ("village/", "minecraft:villages"),
        ("trial_chambers/", "minecraft:trial_chambers"),
    ),
    underground_sets=frozenset({"minecraft:ancient_cities", "minecraft:trial_chambers"}),
)


def wire_graph():
    """红石线：只有模板来源（古代城市），没有世界生成特性。"""
    return graph_of(
        [
            rule(
                "tmpl:redstone_wire",
                "block:minecraft:redstone_wire",
                ("world:minecraft:overworld",),
                family="bindings/template_block",
                kind="places",
                meta={"templates": ["data/minecraft/structure/ancient_city/structures/camp_1.snbt"]},
            ),
            # 玩家放置不是世界生成来源
            rule(
                "place:redstone_wire",
                "block:minecraft:redstone_wire",
                ("item:minecraft:redstone",),
                family="code/place_source",
                kind="places",
            ),
        ]
    )


def ore_graph():
    """铁矿石：有世界生成特性，不是结构专属。"""
    return graph_of(
        [
            rule(
                "wg:iron_ore",
                "block:minecraft:iron_ore",
                ("world:minecraft:overworld",),
                family="worldgen",
                kind="seeds",
                meta={"slot": "block", "source": "feature/ore_iron_upper"},
            ),
            rule(
                "tmpl:iron_ore",
                "block:minecraft:iron_ore",
                ("world:minecraft:overworld",),
                family="bindings/template_block",
                kind="places",
                meta={"templates": ["data/minecraft/structure/village/plains/houses/x.snbt"]},
            ),
        ]
    )


def test_structure_only_detected() -> None:
    placement = PlacementIndex.from_graph(wire_graph())
    fact = placement.of("minecraft:redstone_wire")
    assert fact is not None
    assert fact.structure_only
    assert not fact.has_worldgen


def test_player_placement_is_not_a_source() -> None:
    """`code/place_source` 是玩家放置，不得被当成世界生成事实。"""
    placement = PlacementIndex.from_graph(wire_graph())
    fact = placement.of("minecraft:redstone_wire")
    assert fact is not None
    assert fact.features == ()


def test_block_with_feature_is_not_structure_only() -> None:
    placement = PlacementIndex.from_graph(ore_graph())
    fact = placement.of("minecraft:iron_ore")
    assert fact is not None
    assert not fact.structure_only
    assert fact.has_worldgen


def test_template_to_structure_set() -> None:
    placement = PlacementIndex.from_graph(wire_graph())
    sets = placement.structure_sets("minecraft:redstone_wire", MAPS)
    assert sets == ("minecraft:ancient_cities",)


def test_route_uses_structure_set_for_structure_only_block() -> None:
    placement = PlacementIndex.from_graph(wire_graph())
    sets = placement.structure_sets("minecraft:redstone_wire", MAPS)
    rules = RouteRules(underground_structure_sets=MAPS.underground_sets)
    assert (
        route_module.decide(
            source_type="block_drop",
            subject="minecraft:redstone_wire",
            prereq=("world:minecraft:overworld",),
            rules=rules,
            block_sets=sets,
            structure_only=True,
        )
        == "underground"
    )


def test_surface_structure_keeps_surface_route() -> None:
    """村庄方块在模板里，但村庄本身在地表。"""
    maps = StructureMaps(
        template_prefixes=(("village/", "minecraft:villages"),),
        underground_sets=frozenset({"minecraft:ancient_cities"}),
    )
    graph = graph_of(
        [
            rule(
                "tmpl:door",
                "block:minecraft:acacia_door",
                ("world:minecraft:overworld",),
                family="bindings/template_block",
                kind="places",
                meta={"templates": ["data/minecraft/structure/village/savanna/houses/a.snbt"]},
            )
        ]
    )
    placement = PlacementIndex.from_graph(graph)
    sets = placement.structure_sets("minecraft:acacia_door", maps)
    rules = RouteRules(underground_structure_sets=maps.underground_sets)
    assert (
        route_module.decide(
            source_type="block_drop",
            subject="minecraft:acacia_door",
            prereq=(),
            rules=rules,
            block_sets=sets,
            structure_only=True,
        )
        == "surface"
    )


def test_unknown_block_has_no_fact() -> None:
    placement = PlacementIndex.from_graph(wire_graph())
    assert placement.of("minecraft:not_a_block") is None
    assert placement.structure_sets("minecraft:not_a_block", MAPS) == ()


def test_template_prefix_longest_match() -> None:
    maps = StructureMaps(
        template_prefixes=(
            ("village/", "minecraft:villages"),
            ("village/taiga/", "minecraft:village_taiga"),
        ),
    )
    assert maps.set_for_template("data/minecraft/structure/village/taiga/x.snbt") == "minecraft:village_taiga"
    assert maps.set_for_template("data/minecraft/structure/village/plains/x.snbt") == "minecraft:villages"
