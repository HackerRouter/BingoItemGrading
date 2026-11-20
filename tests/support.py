"""测试用的小型上游图，不依赖 `ref/` 下的真实产物。"""

from __future__ import annotations

from bingo_grading.sources.graph import Graph, Rule


def rule(
    rule_id: str,
    head: str,
    body: tuple[str, ...] = (),
    *,
    family: str = "",
    kind: str = "yield",
    meta: dict | None = None,
) -> Rule:
    return Rule(
        id=rule_id,
        head=head,
        body=body,
        soft=(),
        kind=kind,
        family=family,
        meta=meta or {},
    )


def graph_of(rules: list[Rule], true_nodes: set[str] | None = None) -> Graph:
    graph = Graph(
        label="mini",
        ir_schema=1,
        facts_digest={},
        rules=list(rules),
        true_nodes=frozenset(true_nodes if true_nodes is not None else {rule.head for rule in rules}),
    )
    graph.index()
    return graph


def redstone_graph() -> Graph:
    """红石粉的两条来源：挖矿与地牢箱子；铁锭的配方链用来测合成展开。"""
    rules = [
        rule(
            "loot:redstone_ore",
            "item:minecraft:redstone",
            ("table:minecraft:blocks/redstone_ore", "tool:minecraft:iron_pickaxe"),
            family="loot",
            meta={"table": "minecraft:blocks/redstone_ore", "entry_kind": "item"},
        ),
        rule(
            "loot:simple_dungeon",
            "item:minecraft:redstone",
            ("table:minecraft:chests/simple_dungeon",),
            family="loot",
            meta={"table": "minecraft:chests/simple_dungeon", "entry_kind": "item"},
        ),
        rule(
            "loot:bastion",
            "item:minecraft:redstone",
            ("table:minecraft:chests/bastion_other",),
            family="loot",
            meta={"table": "minecraft:chests/bastion_other", "entry_kind": "item"},
        ),
        rule(
            "bridge:redstone_ore",
            "table:minecraft:blocks/redstone_ore",
            ("block:minecraft:redstone_ore",),
            family="bridge/table",
            kind="holds",
        ),
        rule(
            "bridge:simple_dungeon",
            "table:minecraft:chests/simple_dungeon",
            ("assume:structure_loot",),
            family="bridge/table",
            kind="holds",
        ),
        rule(
            "bridge:bastion",
            "table:minecraft:chests/bastion_other",
            ("assume:structure_loot",),
            family="bridge/table",
            kind="holds",
        ),
        rule(
            "worldgen:redstone_ore",
            "block:minecraft:redstone_ore",
            ("world:minecraft:overworld",),
            family="worldgen",
            kind="seeds",
            meta={"slot": "block", "worldgen_kind": "feature"},
        ),
        rule(
            "recipe:redstone_block",
            "item:minecraft:redstone",
            ("item:minecraft:redstone_block",),
            family="recipes",
            meta={"count": 9, "serializer": "minecraft:crafting_shapeless"},
        ),
        # 铁锭：直接来源没有挖掘，挖掘只能经配方链到铁矿石
        rule(
            "recipe:iron_ingot_from_iron_ore",
            "item:minecraft:iron_ingot",
            ("item:minecraft:iron_ore", "station:minecraft:furnace"),
            family="recipes",
        ),
        rule(
            "loot:iron_ore",
            "item:minecraft:iron_ore",
            ("table:minecraft:blocks/iron_ore", "tool:minecraft:stone_pickaxe"),
            family="loot",
            meta={"table": "minecraft:blocks/iron_ore", "entry_kind": "item"},
        ),
        rule(
            "bridge:iron_ore",
            "table:minecraft:blocks/iron_ore",
            ("block:minecraft:iron_ore",),
            family="bridge/table",
            kind="holds",
        ),
        rule(
            "worldgen:iron_ore",
            "block:minecraft:iron_ore",
            ("world:minecraft:overworld",),
            family="worldgen",
            kind="seeds",
            meta={"slot": "block", "worldgen_kind": "feature"},
        ),
        # 回收环：铁锭 → 铁粒 → 铁镐（需铁锭与木棍）→ 熔炼回铁粒
        rule(
            "recipe:iron_nugget_from_ingot",
            "item:minecraft:iron_nugget",
            ("item:minecraft:iron_ingot",),
            family="recipes",
        ),
        rule(
            "recipe:iron_pickaxe",
            "item:minecraft:iron_pickaxe",
            ("item:minecraft:iron_ingot", "tag:item/minecraft:tool_materials"),
            family="recipes",
        ),
        rule(
            "recipe:iron_nugget_from_pickaxe",
            "item:minecraft:iron_nugget",
            ("item:minecraft:iron_pickaxe",),
            family="recipes",
        ),
        # 一个交易来源，subject 用职业/等级
        rule(
            "trade:cleric_redstone",
            "item:minecraft:redstone",
            ("assume:villager_trade", "item:minecraft:emerald"),
            family="trades",
            meta={"profession": "cleric", "level": 1},
        ),
        # tag 与嵌套 tag
        rule("tag:planks:oak", "tag:item/minecraft:planks", ("item:minecraft:oak_planks",), family="bridge/tag", kind="implies"),
        rule("tag:tool:planks", "tag:item/minecraft:tool_materials", ("tag:item/minecraft:planks",), family="bridge/tag", kind="implies"),
        # 木棍：树叶概率掉落，用来测概率表
        rule(
            "loot:stick_leaves",
            "item:minecraft:stick",
            ("table:minecraft:blocks/oak_leaves",),
            family="loot",
            meta={"table": "minecraft:blocks/oak_leaves", "entry_kind": "item"},
        ),
        rule("bridge:oak_leaves", "table:minecraft:blocks/oak_leaves", ("block:minecraft:oak_leaves",), family="bridge/table", kind="holds"),
        rule(
            "worldgen:oak_leaves",
            "block:minecraft:oak_leaves",
            ("world:minecraft:overworld",),
            family="worldgen",
            kind="seeds",
            meta={"slot": "block", "worldgen_kind": "feature"},
        ),
    ]
    true_nodes = {rule.head for rule in rules} | {"item:minecraft:iron_pickaxe", "item:minecraft:oak_planks"}
    return graph_of(rules, true_nodes)
