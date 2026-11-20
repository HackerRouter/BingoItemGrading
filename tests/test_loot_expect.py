"""战利品表期望引擎。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bingo_grading.loot.expect import expect, probability_at_least_once
from bingo_grading.loot.tables import LootTableError, load


def write_pack(root: Path, tables: dict[str, dict], namespace: str = "minecraft") -> Path:
    base = root / "data" / namespace / "loot_table"
    for table_id, doc in tables.items():
        path = base / f"{table_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc), encoding="utf-8")
    (root / "pack.mcmeta").write_text('{"pack": {}}', encoding="utf-8")
    return root


def item(name: str, **extra) -> dict:
    return {"type": "minecraft:item", "name": name, **extra}


def test_single_pool_single_item(tmp_path: Path) -> None:
    pack = write_pack(
        tmp_path / "pack",
        {
            "chests/t": {
                "pools": [
                    {"rolls": 3, "entries": [item("minecraft:coal")]},
                ]
            }
        },
    )
    tables = load([pack])
    result = expect("minecraft:chests/t", tables)
    assert result.per_item["minecraft:coal"] == pytest.approx(3.0)
    assert result.total_items == pytest.approx(3.0)


def test_weight_distribution(tmp_path: Path) -> None:
    pack = write_pack(
        tmp_path / "pack",
        {
            "chests/t": {
                "pools": [
                    {
                        "rolls": 100,
                        "entries": [
                            item("minecraft:a", weight=3),
                            item("minecraft:b", weight=1),
                        ],
                    }
                ]
            }
        },
    )
    tables = load([pack])
    result = expect("minecraft:chests/t", tables)
    assert result.per_item["minecraft:a"] == pytest.approx(75.0)
    assert result.per_item["minecraft:b"] == pytest.approx(25.0)


def test_missing_weight_defaults_to_one(tmp_path: Path) -> None:
    pack = write_pack(
        tmp_path / "pack",
        {
            "chests/t": {
                "pools": [
                    {
                        "rolls": 2,
                        "entries": [
                            item("minecraft:a"),
                            {"type": "minecraft:item", "name": "minecraft:b", "weight": 3},
                        ],
                    }
                ]
            }
        },
    )
    tables = load([pack])
    result = expect("minecraft:chests/t", tables)
    # 权重 1 : 3
    assert result.per_item["minecraft:a"] == pytest.approx(0.5)
    assert result.per_item["minecraft:b"] == pytest.approx(1.5)


def test_uniform_rolls_and_set_count(tmp_path: Path) -> None:
    pack = write_pack(
        tmp_path / "pack",
        {
            "chests/t": {
                "pools": [
                    {
                        "rolls": {"type": "minecraft:uniform", "min": 1, "max": 3},
                        "entries": [
                            item(
                                "minecraft:bone",
                                modifier={
                                    "type": "minecraft:set_count",
                                    "count": {"type": "minecraft:uniform", "min": 1, "max": 8},
                                },
                            )
                        ],
                    }
                ]
            }
        },
    )
    tables = load([pack])
    result = expect("minecraft:chests/t", tables)
    # E[rolls]=2, E[count]=4.5
    assert result.per_item["minecraft:bone"] == pytest.approx(9.0)


def test_binomial_count(tmp_path: Path) -> None:
    pack = write_pack(
        tmp_path / "pack",
        {
            "chests/t": {
                "pools": [
                    {
                        "rolls": 1,
                        "entries": [
                            item(
                                "minecraft:x",
                                modifier={
                                    "type": "minecraft:set_count",
                                    "count": {"type": "minecraft:binomial", "n": 10, "p": 0.25},
                                },
                            )
                        ],
                    }
                ]
            }
        },
    )
    tables = load([pack])
    result = expect("minecraft:chests/t", tables)
    assert result.per_item["minecraft:x"] == pytest.approx(2.5)


def test_table_bonus_uses_no_enchant_level(tmp_path: Path) -> None:
    pack = write_pack(
        tmp_path / "pack",
        {
            "blocks/leaves": {
                "pools": [
                    {
                        "rolls": 1,
                        "entries": [
                            item(
                                "minecraft:stick",
                                condition={
                                    "type": "minecraft:table_bonus",
                                    "chances": [0.02, 0.022, 0.025],
                                },
                            )
                        ],
                    }
                ]
            }
        },
    )
    tables = load([pack])
    result = expect("minecraft:blocks/leaves", tables)
    assert result.per_item["minecraft:stick"] == pytest.approx(0.02)
    assert any("无附魔级" in text for text in result.assumptions)


def test_entry_condition_multiplied(tmp_path: Path) -> None:
    """条目自身条件必须乘进去；漏了会让概率变成 1。"""
    pack = write_pack(
        tmp_path / "pack",
        {
            "chests/t": {
                "pools": [
                    {
                        "rolls": 1,
                        "entries": [
                            item("minecraft:rare", condition={"type": "minecraft:random_chance", "chance": 0.1})
                        ],
                    }
                ]
            }
        },
    )
    tables = load([pack])
    result = expect("minecraft:chests/t", tables)
    assert result.per_item["minecraft:rare"] == pytest.approx(0.1)


def test_pool_condition_multiplied(tmp_path: Path) -> None:
    pack = write_pack(
        tmp_path / "pack",
        {
            "chests/t": {
                "pools": [
                    {
                        "rolls": 1,
                        "condition": {"type": "minecraft:random_chance", "chance": 0.5},
                        "entries": [item("minecraft:x")],
                    }
                ]
            }
        },
    )
    tables = load([pack])
    assert expect("minecraft:chests/t", tables).per_item["minecraft:x"] == pytest.approx(0.5)


def test_alternatives_first_match(tmp_path: Path) -> None:
    pack = write_pack(
        tmp_path / "pack",
        {
            "blocks/leaves": {
                "pools": [
                    {
                        "rolls": 1,
                        "entries": [
                            {
                                "type": "minecraft:alternatives",
                                "children": [
                                    item(
                                        "minecraft:leaves",
                                        condition={"type": "minecraft:tool/can_shear"},
                                    ),
                                    item(
                                        "minecraft:sapling",
                                        condition={"type": "minecraft:random_chance", "chance": 0.05},
                                    ),
                                ],
                            }
                        ],
                    }
                ]
            }
        },
    )
    tables = load([pack])

    with_tool = expect("minecraft:blocks/leaves", tables, tool_probability=1.0)
    assert with_tool.per_item["minecraft:leaves"] == pytest.approx(1.0)
    assert "minecraft:sapling" not in with_tool.per_item

    bare = expect("minecraft:blocks/leaves", tables, tool_probability=0.0)
    assert bare.per_item["minecraft:sapling"] == pytest.approx(0.05)
    assert "minecraft:leaves" not in bare.per_item


def test_group_gives_all_children(tmp_path: Path) -> None:
    pack = write_pack(
        tmp_path / "pack",
        {
            "chests/t": {
                "pools": [
                    {
                        "rolls": 1,
                        "entries": [
                            {
                                "type": "minecraft:group",
                                "children": [item("minecraft:a"), item("minecraft:b")],
                            }
                        ],
                    }
                ]
            }
        },
    )
    tables = load([pack])
    result = expect("minecraft:chests/t", tables)
    assert result.per_item["minecraft:a"] == pytest.approx(1.0)
    assert result.per_item["minecraft:b"] == pytest.approx(1.0)


def test_nested_table_is_followed(tmp_path: Path) -> None:
    pack = write_pack(
        tmp_path / "pack",
        {
            "chests/outer": {
                "pools": [
                    {
                        "rolls": 1,
                        "entries": [{"type": "minecraft:loot_table", "name": "minecraft:chests/inner"}],
                    }
                ]
            },
            "chests/inner": {"pools": [{"rolls": 2, "entries": [item("minecraft:gold")]}]},
        },
    )
    tables = load([pack])
    assert expect("minecraft:chests/outer", tables).per_item["minecraft:gold"] == pytest.approx(2.0)


def test_empty_and_dynamic_are_reported(tmp_path: Path) -> None:
    pack = write_pack(
        tmp_path / "pack",
        {
            "chests/t": {
                "pools": [
                    {
                        "rolls": 1,
                        "entries": [
                            {"type": "minecraft:empty"},
                            {"type": "minecraft:dynamic", "name": "minecraft:shulker_box"},
                        ],
                    }
                ]
            }
        },
    )
    tables = load([pack])
    result = expect("minecraft:chests/t", tables)
    assert result.total_items == 0
    assert any("dynamic" in text for text in result.unsupported)


def test_pack_override_wins(tmp_path: Path) -> None:
    vanilla = write_pack(
        tmp_path / "vanilla",
        {"chests/t": {"pools": [{"rolls": 1, "entries": [item("minecraft:a")]}]}},
    )
    pack = write_pack(
        tmp_path / "pack",
        {"chests/t": {"pools": [{"rolls": 5, "entries": [item("minecraft:b")]}]}},
    )
    tables = load([vanilla, pack])
    result = expect("minecraft:chests/t", tables)
    assert result.per_item["minecraft:b"] == pytest.approx(5.0)
    assert "minecraft:a" not in result.per_item
    assert str(pack) in str(tables.sources["minecraft:chests/t"])


def test_missing_table_raises(tmp_path: Path) -> None:
    pack = write_pack(tmp_path / "pack", {"chests/t": {"pools": []}})
    tables = load([pack])
    with pytest.raises(LootTableError):
        expect("minecraft:chests/absent", tables)


def test_empty_pack_raises(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(LootTableError):
        load([empty])


def test_probability_at_least_once() -> None:
    assert probability_at_least_once(0.1, 0) == 0.0
    assert probability_at_least_once(0.0, 10) == 0.0
    assert probability_at_least_once(0.1, 10) == pytest.approx(1 - 0.3679, abs=1e-3)
