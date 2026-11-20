"""结构内容与交易两个导入器、以及标签展开的单元测试。"""

from __future__ import annotations

import json
from pathlib import Path

from bingo_grading.loot.expect import expect
from bingo_grading.loot.tables import load
from bingo_grading.stats.importers import structure as structure_import
from bingo_grading.stats.importers import trade as trade_import
from bingo_grading.tags import TagSet


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------- 结构内容


def _facts_dir(tmp_path: Path) -> Path:
    facts = tmp_path / "facts"
    write_jsonl(
        facts / "structures.jsonl",
        [
            {
                "structure": "minecraft:village_plains",
                "start_pool": "minecraft:village/plains/town_centers",
                "size": 6,
                "pools": [
                    {
                        "pool": "minecraft:village/plains/houses",
                        "templates": [
                            {"template": "village/plains/houses/a", "weight": 1},
                            {"template": "village/plains/houses/b", "weight": 1},
                        ],
                    }
                ],
            }
        ],
    )
    write_jsonl(
        facts / "template_containers.jsonl",
        [
            {
                "template": "village/plains/houses/a",
                "block_entity": "minecraft:chest",
                "pos": [1, 1, 1],
                "table": "minecraft:chests/village_plains_house",
            },
            {
                "template": "village/plains/houses/a",
                "block_entity": "minecraft:barrel",
                "pos": [2, 1, 1],
                "table": "minecraft:chests/village_plains_house",
            },
        ],
    )
    write_jsonl(
        facts / "template_blocks.jsonl",
        [
            {"template": "village/plains/houses/a", "block": "minecraft:oak_planks", "state": "", "count": 10},
            {"template": "village/plains/houses/b", "block": "minecraft:oak_planks", "state": "", "count": 20},
        ],
    )
    return facts


def _run_dir(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    write_json(
        run / "structure-interior.json",
        {"ok": True, "resultFiles": {"minecraft:overworld": "structure-interior.overworld.json"}},
    )
    write_json(
        run / "structure-interior.overworld.json",
        {
            "ok": True,
            "result": {
                "minecraft:overworld": {
                    "structures": [
                        {
                            "structure": "minecraft:village_plains",
                            "starts": 4,
                            "piecesPerStart": 2.0,
                            # 每个实例放 2 个 a 模板，a 里有 2 个容器 → 4 个/实例，与实测一致
                            "templates": [
                                {
                                    "template": "minecraft:village/plains/houses/a",
                                    "count": 8,
                                    "perStart": 2.0,
                                    "share": 1.0,
                                }
                            ],
                            "containers": {"minecraft:chest": 16},
                            "lootTables": {"minecraft:chests/village_plains_house": 16},
                        },
                        {
                            "structure": "minecraft:monument",
                            "starts": 2,
                            "containers": {"minecraft:chest": 6},
                            "lootTables": {"minecraft:chests/monument": 6},
                        },
                    ],
                    "dungeons": {
                        "count": 2,
                        "containersPerDungeon": 1.5,
                        "lootTables": {"minecraft:chests/simple_dungeon": 3},
                        "byKind": {"zombie": 2},
                    },
                }
            },
        },
    )
    return run


def test_templates_are_the_primary_source(tmp_path: Path) -> None:
    rows, report = structure_import.build(
        run_dir=_run_dir(tmp_path),
        facts_dir=_facts_dir(tmp_path),
        pack_version="test",
    )

    village = [
        row
        for row in rows
        if row.subject == "minecraft:village_plains" and row.condition == "source=template"
    ]
    assert len(village) == 1
    value = village[0].value
    # 两个模板、共 2 个容器 → 每模板 1 个
    assert value["containers"] == 1.0
    assert value["loot_tables"] == {"minecraft:chests/village_plains_house": 1.0}
    assert value["templates"] == 2
    assert value["templates_with_containers"] == 1
    assert value["blocks"] == {"minecraft:oak_planks": 15.0}
    assert report["template"]["structures"] == 1


def test_measured_fills_only_subjects_without_templates(tmp_path: Path) -> None:
    rows, report = structure_import.build(
        run_dir=_run_dir(tmp_path),
        facts_dir=_facts_dir(tmp_path),
        pack_version="test",
    )

    # 有模板的结构不再出实测行
    assert not [
        row
        for row in rows
        if row.subject == "minecraft:village_plains" and row.condition == "source=measured"
    ]
    assert report["measured"]["skipped"] == 1

    # 没有模板的：monument 与环境自带的 monster_room 用实测
    monument = next(row for row in rows if row.subject == "minecraft:monument")
    assert monument.value["source"] == "measured"
    assert monument.value["containers"] == 3.0
    assert monument.value["starts"] == 2

    dungeon = next(row for row in rows if row.subject == structure_import.DUNGEON_SUBJECT)
    assert dungeon.value["containers"] == 1.5
    assert dungeon.value["loot_tables"] == {"minecraft:chests/simple_dungeon": 1.5}


def test_composition_matches_measurement_when_templates_are_complete(tmp_path: Path) -> None:
    rows, report = structure_import.build(
        run_dir=_run_dir(tmp_path),
        facts_dir=_facts_dir(tmp_path),
        pack_version="test",
    )
    village = next(
        row
        for row in rows
        if row.subject == "minecraft:village_plains" and row.condition == "source=template"
    )
    # 每实例 2 个 a 模板 × 每个模板 2 个容器 = 4 个/实例，与实测一致
    assert village.value["templates_matched"] == village.value["templates_placed"] == 1
    assert village.value["containers_per_start"] == 4.0
    assert report["reliable"] == ["minecraft:village_plains"]


def test_unreliable_composition_falls_back_to_measurement(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)
    path = run / "structure-interior.overworld.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    village = payload["result"]["minecraft:overworld"]["structures"][0]
    village["templates"][0]["perStart"] = 0.5  # 合成只有 1.0，实测 4.0 → 不可靠
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    rows, report = structure_import.build(
        run_dir=run, facts_dir=_facts_dir(tmp_path), pack_version="test"
    )
    template_row = next(
        row
        for row in rows
        if row.subject == "minecraft:village_plains" and row.condition == "source=template"
    )
    # 按实例的口径撤掉，内容身份保留
    assert "containers_per_start" not in template_row.value
    assert template_row.value["templates"] == 2
    assert "minecraft:village_plains" in report["unreliable"]
    # 并且补出实测行
    measured = next(
        row
        for row in rows
        if row.subject == "minecraft:village_plains" and row.condition == "source=measured"
    )
    assert measured.value["containers"] == 4.0


def test_without_template_facts_everything_is_measured(tmp_path: Path) -> None:
    rows, _ = structure_import.build(
        run_dir=_run_dir(tmp_path), facts_dir=None, pack_version="test"
    )
    assert {row.condition for row in rows} == {"source=measured"}


def test_missing_products_are_empty(tmp_path: Path) -> None:
    rows, report = structure_import.build(
        run_dir=tmp_path / "nothing", facts_dir=None, pack_version="test"
    )
    assert rows == []
    assert report["rows"] == 0


# ---------------------------------------------------------------- 交易


def _trade_row(payload: dict, status: str = "parsed") -> str:
    return json.dumps(
        {
            "kind": "trade",
            "payload": payload,
            "prov": {"file": "x", "input": "src"},
            "status": status,
        },
        ensure_ascii=False,
    )


def test_trade_set_expands_through_tag(tmp_path: Path) -> None:
    facts = tmp_path / "trade.jsonl"
    facts.write_text(
        "\n".join(
            [
                _trade_row(
                    {
                        "layer": "offer",
                        "profession": "farmer",
                        "level": 1,
                        "trade": "minecraft:farmer/1/wheat_emerald",
                        "wants": {"id": "minecraft:wheat", "count": 20},
                        "gives": {"id": "minecraft:emerald", "count": 1},
                        "meta": {"max_uses": 16},
                    }
                ),
                _trade_row(
                    {
                        "layer": "offer",
                        "profession": "farmer",
                        "level": 1,
                        "trade": "minecraft:farmer/1/carrot_emerald",
                        "wants": {"id": "minecraft:carrot", "count": 22},
                        "gives": {"id": "minecraft:emerald", "count": 1},
                        "meta": {"max_uses": 16},
                    }
                ),
                _trade_row(
                    {
                        "layer": "set",
                        "profession": "farmer",
                        "level": 1,
                        "trades_ref": "#minecraft:farmer/level_1",
                    }
                ),
                _trade_row({}, status="partial"),
            ]
        ),
        encoding="utf-8",
    )

    tags = TagSet(
        by_registry={
            "minecraft:villager_trade": {
                "minecraft:farmer/level_1": (
                    "minecraft:farmer/1/wheat_emerald",
                    "minecraft:farmer/1/carrot_emerald",
                )
            }
        }
    )

    rows, report = trade_import.build(
        facts_path=facts, pack_version="test", tags=tags, provenance="test"
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.subject == "minecraft:farmer/1"
    assert row.value["offer_count"] == 2
    # 两条等价交易都保留：选哪条是调用方的事
    assert [offer["wants"][0]["count"] for offer in row.value["offers"]] == [22, 20]
    assert report["partial"] == 1
    assert report["unresolved"] == []


def test_trade_count_range_takes_midpoint(tmp_path: Path) -> None:
    """附魔书的报价数量是区间（vanilla 5–64），取中点而不是退回 1。

    退回 1 会让附魔书便宜几十倍，比路线缺席更糟；区间也无法当整数用。
    """
    facts = tmp_path / "trade.jsonl"
    facts.write_text(
        _trade_row(
            {
                "layer": "offer",
                # 不带 `level`：走「无等级职业」那条聚合路径，一行即可成组。
                "profession": "librarian",
                "trade": "minecraft:librarian/1/emerald_and_book_enchanted_book",
                "wants": [{"id": "minecraft:emerald", "count": {"min": 5, "max": 64}}],
                "additional_wants": [{"id": "minecraft:book", "count": 1}],
                "gives": {"id": "minecraft:enchanted_book", "count": 1},
                "meta": {"max_uses": 12},
            }
        ),
        encoding="utf-8",
    )

    rows, _report = trade_import.build(
        facts_path=facts, pack_version="test", tags=None
    )
    assert len(rows) == 1
    offer = rows[0].value["offers"][0]
    assert offer["wants"][0] == {"id": "minecraft:emerald", "count": 35}


def test_trade_set_without_tags_is_reported(tmp_path: Path) -> None:
    facts = tmp_path / "trade.jsonl"
    facts.write_text(
        _trade_row(
            {
                "layer": "set",
                "profession": "mason",
                "level": 1,
                "trades_ref": "#minecraft:mason/level_1",
            }
        ),
        encoding="utf-8",
    )
    rows, report = trade_import.build(facts_path=facts, pack_version="test", tags=None)
    assert rows == []
    assert report["unresolved"]


# ---------------------------------------------------------------- 标签与 tag 条目


def test_tag_expand_is_recursive_and_deduplicated() -> None:
    tags = TagSet(
        by_registry={
            "minecraft:item": {
                "a": ("#b", "minecraft:one"),
                "b": ("minecraft:two", "minecraft:one"),
            }
        }
    )
    assert tags.expand("a") == ("minecraft:two", "minecraft:one")


def test_loot_tag_entry_is_expanded(tmp_path: Path) -> None:
    root = tmp_path / "vanilla" / "minecraft" / "loot_table"
    write_json(
        root / "entities" / "thing.json",
        {
            "type": "minecraft:entity",
            "pools": [
                {
                    "rolls": 1,
                    "entries": [
                        {"type": "minecraft:tag", "expand": True, "items": "#minecraft:discs"}
                    ],
                }
            ],
        },
    )
    tables = load([root])
    tags = TagSet(
        by_registry={
            "minecraft:item": {
                "minecraft:discs": ("minecraft:disc_a", "minecraft:disc_b"),
            }
        }
    )

    with_tags = expect("minecraft:entities/thing", tables, tags=tags)
    assert with_tags.per_item == {"minecraft:disc_a": 0.5, "minecraft:disc_b": 0.5}
    assert with_tags.unsupported == []

    # 没有标签数据时不静默当成 0，而是记进 unsupported
    without = expect("minecraft:entities/thing", tables)
    assert without.per_item == {}
    assert any("tag 条目未展开" in note for note in without.unsupported)
