"""`CaseContext` 的两个取数算子：结构内容（模板优先）与交易报价。"""

from __future__ import annotations

from bingo_grading.case.context import CaseContext
from bingo_grading.stats.model import WorldStat, WorldStatStore


def _store(*rows: WorldStat) -> WorldStatStore:
    store = WorldStatStore()
    for row in rows:
        store.add(row)
    return store


def _row(stat_type: str, subject: str, value: dict, **overrides) -> WorldStat:
    payload = {
        "pack_version": "test",
        "scope_level": "global",
        "dimension": "",
        "biome": "",
        "stat_type": stat_type,
        "subject": subject,
        "condition": "",
        "value": value,
        "sample_size": 4,
        "confidence": "medium",
        "derived_from": (),
        "provenance": "",
        "note": "",
    }
    payload.update(overrides)
    return WorldStat(**payload)


def test_structure_content_prefers_templates_over_measurements() -> None:
    template = _row(
        "structure_content",
        "minecraft:village_plains",
        {
            "source": "template",
            "containers": 0.2,
            "loot_tables": {"minecraft:chests/village_plains_house": 0.2},
            "templates": 145,
        },
        condition="source=template",
    )
    measured = _row(
        "structure_content",
        "minecraft:village_plains",
        {
            "source": "measured",
            "containers": 3.9,
            "loot_tables": {"minecraft:chests/village_plains_house": 3.9},
            "starts": 10,
        },
        scope_level="dimension",
        dimension="minecraft:overworld",
        condition="source=measured",
    )
    context = CaseContext(store=_store(template, measured))

    found = context.structure_content("minecraft:village_plains")
    assert found is not None
    value, origin = found
    assert value["source"] == "template"
    assert value["containers"] == 0.2
    assert origin == "structure_content:minecraft:village_plains[template]"

    # 显式要实测时才给实测
    measured_only = context.structure_content("minecraft:village_plains", source="measured")
    assert measured_only is not None
    assert measured_only[0]["containers"] == 3.9

    # 实测行是维度级的：换维度就取不到
    assert (
        context.structure_content(
            "minecraft:village_plains", source="measured", dimension="minecraft:the_nether"
        )
        is None
    )
    assert context.structure_content("minecraft:monument") is None


def test_trade_offers_keep_equivalent_trades() -> None:
    offers = [
        {
            "wants": [{"id": "minecraft:wheat", "count": 20}],
            "gives": {"id": "minecraft:emerald", "count": 1},
        },
        {
            "wants": [{"id": "minecraft:carrot", "count": 22}],
            "gives": {"id": "minecraft:emerald", "count": 1},
        },
    ]
    store = _store(
        _row("trade_offer", "minecraft:farmer/1", {"offers": offers, "offer_count": 2})
    )
    context = CaseContext(store=store)

    found = context.trade_offers("farmer", 1)
    assert found is not None
    got, origin = found
    assert [offer["wants"][0]["count"] for offer in got] == [20, 22]
    assert origin == "trade_offer:minecraft:farmer/1"

    assert context.trade_offers("farmer", 2) is None
