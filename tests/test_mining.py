"""挖掘代价换算。"""

from __future__ import annotations

import math

import pytest

from bingo_grading import gamedata, mining_facts, units
from bingo_grading.mining import (
    CHUNK_FOOTPRINT,
    MiningError,
    blocks_per_item,
    estimate,
    estimate_from_row,
    shaft_cost,
    surrounding_block,
    tunnel_cost,
    volume_density,
)


def section(low: int, high: int, per_chunk: float) -> dict:
    return {
        str(low): {
            "y_range": [low, high],
            "count": 1,
            "per_chunk": per_chunk,
        }
    }


def test_volume_density_divides_by_section_height() -> None:
    # 每区块 16 块，段高 16 → 每方块³ 16/(256*16)
    assert volume_density(16.0, 16) == pytest.approx(16.0 / (CHUNK_FOOTPRINT * 16))


def test_volume_density_rejects_bad_height() -> None:
    with pytest.raises(MiningError):
        volume_density(1.0, 0)


def test_blocks_per_item() -> None:
    assert blocks_per_item(0.001) == pytest.approx(1000.0)
    assert blocks_per_item(0.0) == math.inf


def test_tunnel_cost_scales_linearly() -> None:
    density = 0.001  # 每方块³
    one = tunnel_cost(density, target_items=1.0)
    two = tunnel_cost(density, target_items=2.0)
    assert two == pytest.approx(one * 2)


def test_tunnel_cost_formula() -> None:
    """挖 1 块方块耗时 = 1000 × 秒数 ÷ 秒每 TU。"""
    density = 0.001  # 撞到 1 块要挖 1000 个方块
    cost = tunnel_cost(density, break_seconds=0.4)
    assert cost == pytest.approx(1000 * 0.4 / units.SECONDS_PER_TU)


def test_tunnel_cost_infinite_when_empty() -> None:
    assert math.isinf(tunnel_cost(0.0))


def test_shaft_cost_counts_blocks_and_swath() -> None:
    # 30 格深，每格 0.4 秒，截面 1×2
    assert shaft_cost(70, 40, break_seconds=0.4) == pytest.approx(
        30 * gamedata.DEFAULT_SWATH * 0.4 / units.SECONDS_PER_TU
    )
    # 上下对称
    assert shaft_cost(40, 70, break_seconds=0.4) == pytest.approx(shaft_cost(70, 40, break_seconds=0.4))


def test_surrounding_block_by_level() -> None:
    assert surrounding_block(100) == "stone"
    assert surrounding_block(0) == "stone"
    assert surrounding_block(-1) == "deepslate"
    assert surrounding_block(-50) == "deepslate"


def test_surrounding_block_in_nether_is_netherrack() -> None:
    """下界整块都是下界岩，没有深板岩/石头之分。"""
    assert surrounding_block(100, "minecraft:the_nether") == "netherrack"
    assert surrounding_block(-50, "minecraft:the_nether") == "netherrack"


def test_surface_y_per_dimension() -> None:
    from bingo_grading.mining import surface_y_for

    assert surface_y_for("minecraft:overworld") == 70
    assert surface_y_for("minecraft:the_nether") == 50
    assert surface_y_for("minecraft:unknown") == 70


def test_nether_estimate_is_cheaper_than_stone() -> None:
    """同密度下界岩比石头软 4 倍，矿道代价也应约 1/4。"""
    stone = estimate(
        biome="x",
        subject="y",
        sections=section(64, 79, 10.0),
        dimension="minecraft:overworld",
    )
    nether = estimate(
        biome="x",
        subject="y",
        sections=section(64, 79, 10.0),
        dimension="minecraft:the_nether",
    )
    assert stone.best is not None and nether.best is not None
    assert nether.best.break_block == "netherrack"
    ratio = nether.best.tunnel_tu / stone.best.tunnel_tu
    assert ratio == pytest.approx(
        mining_facts.break_seconds("netherrack", material=gamedata.UNDERGROUND_MINING_MATERIAL)
        / mining_facts.break_seconds("stone", material=gamedata.UNDERGROUND_MINING_MATERIAL)
    )


def test_nether_shaft_starts_at_nether_surface() -> None:
    nether = estimate(
        biome="x",
        subject="y",
        sections=section(48, 63, 10.0),
        dimension="minecraft:the_nether",
    )
    assert nether.best is not None
    # y=50 到段中心 55 → 5 格，按 1×2 截面
    assert nether.best.shaft_tu == pytest.approx(
        5
        * gamedata.DEFAULT_SWATH
        * mining_facts.break_seconds("netherrack", material=gamedata.UNDERGROUND_MINING_MATERIAL)
        / units.SECONDS_PER_TU
    )


def test_estimate_picks_richest_section() -> None:
    """两个段：低段稀、高段富。应选高段（矿道短）。"""
    result = estimate(
        biome="minecraft:test",
        subject="minecraft:gold_ore",
        sections={
            **section(0, 15, 0.5),
            **section(48, 63, 20.0),
        },
        surface_y=70,
    )
    assert result.best is not None
    assert result.best.y_range == (48, 63)


def test_estimate_accounts_for_shaft_depth() -> None:
    """密度相同时，浅的段更优（竖井短）。"""
    result = estimate(
        biome="minecraft:test",
        subject="minecraft:gold_ore",
        sections={
            **section(-64, -49, 10.0),
            **section(48, 63, 10.0),
        },
        surface_y=70,
    )
    assert result.best is not None
    assert result.best.y_range == (48, 63)


def test_estimate_deep_section_uses_deepslate() -> None:
    result = estimate(
        biome="minecraft:test",
        subject="minecraft:redstone_ore",
        sections=section(-64, -49, 10.0),
        surface_y=70,
    )
    assert result.best is not None
    assert result.best.break_block == "deepslate"


def test_estimate_explicit_block_overrides_level() -> None:
    result = estimate(
        biome="minecraft:test",
        subject="minecraft:redstone_ore",
        sections=section(-64, -49, 10.0),
        break_block="stone",
    )
    assert result.best is not None
    assert result.best.break_block == "stone"


def test_estimate_drops_zero_density_sections() -> None:
    result = estimate(
        biome="minecraft:test",
        subject="minecraft:gold_ore",
        sections={**section(0, 15, 0.0), **section(48, 63, 5.0)},
    )
    assert len(result.sections) == 1
    assert result.best is not None
    assert result.best.y_range == (48, 63)


def test_estimate_empty_sections_is_inf() -> None:
    result = estimate(biome="minecraft:test", subject="minecraft:gold_ore", sections={})
    assert result.cost_tu is None
    assert any("没有纵段" in note for note in result.assumptions)


def test_estimate_all_zero_is_inf() -> None:
    result = estimate(
        biome="minecraft:test",
        subject="minecraft:gold_ore",
        sections=section(0, 15, 0.0),
    )
    assert result.cost_tu is None


def test_entries_per_block_reduces_cost() -> None:
    """红石矿一块掉 4.5 个，拿 1 个只要挖 1/4.5 块矿。"""
    base = estimate(
        biome="minecraft:test",
        subject="minecraft:redstone_ore",
        sections=section(0, 15, 10.0),
    )
    boosted = estimate(
        biome="minecraft:test",
        subject="minecraft:redstone_ore",
        sections=section(0, 15, 10.0),
        entries_per_block=4.5,
    )
    assert base.cost_tu is not None and boosted.cost_tu is not None
    # 矿道部分按比例下降；竖井不变，所以总比不到 4.5 倍
    assert boosted.cost_tu < base.cost_tu
    assert boosted.assumptions != base.assumptions


def test_rich_section_cost_is_not_floored() -> None:
    """极富的段代价远小于 1 TU 时保留真值，不抬到下限。

    这里每区块 10 万块，算出来不到 1 TU。旧的 `COST_FLOOR` 会把它抬到 1 TU，
    而拿几百个时真实耗时是「0.7 × 500」而不是「1 × 500」——抬高会让
    「矿富的地方便宜」这类结论失真。
    """
    result = estimate(
        biome="minecraft:test",
        subject="minecraft:gold_ore",
        sections=section(64, 79, 100000.0),
        surface_y=70,
    )
    assert result.cost_tu is not None
    assert 0 < result.cost_tu < 1.0


def test_unknown_block_raises() -> None:
    with pytest.raises(MiningError, match="未知方块类型"):
        estimate(
            biome="minecraft:test",
            subject="minecraft:gold_ore",
            sections=section(0, 15, 1.0),
            break_block="cheese",
        )


def test_bad_entries_per_block_raises() -> None:
    with pytest.raises(MiningError):
        estimate(
            biome="minecraft:test",
            subject="minecraft:gold_ore",
            sections=section(0, 15, 1.0),
            entries_per_block=0,
        )


class StubRow:
    def __init__(self, biome: str, subject: str, value: dict) -> None:
        self.biome = biome
        self.subject = subject
        self.value = value


def test_estimate_from_row_propagates_chunk_reliability() -> None:
    """上游的区块级 reliable 只做记录，不决定代价可用性。"""
    row = StubRow(
        "minecraft:badlands",
        "minecraft:gold_ore",
        {
            "per_chunk_density": 11.0,
            "reliable": False,
            "total_blocks": 483,
            "by_section": section(32, 47, 11.0),
        },
    )
    result = estimate_from_row(row)
    assert result.chunk_reliable is False
    # 483 块样本足够，不该因为覆盖区块少就标成不可信
    assert result.density_trusted is True
    assert not any("样本不足" in note for note in result.assumptions)


def test_few_blocks_is_untrusted() -> None:
    """数到的方块太少才不可信。"""
    row = StubRow(
        "minecraft:lush_caves",
        "minecraft:redstone_ore",
        {
            "per_chunk_density": 10.0,
            "reliable": False,
            "total_blocks": 2,
            "by_section": section(0, 15, 10.0),
        },
    )
    result = estimate_from_row(row)
    assert result.density_trusted is False
    assert result.sample_blocks == 2
    assert any("样本不足" in note for note in result.assumptions)


def test_density_trusted_is_none_without_block_count() -> None:
    row = StubRow(
        "minecraft:test",
        "minecraft:gold_ore",
        {"per_chunk_density": 1.0, "by_section": section(0, 15, 1.0)},
    )
    assert estimate_from_row(row).density_trusted is None


def test_block_count_wins_over_chunk_count() -> None:
    """覆盖区块远超阈值但只数到几块，仍算不可信。"""
    row = StubRow(
        "minecraft:test",
        "minecraft:gold_ore",
        {
            "per_chunk_density": 0.01,
            "reliable": True,
            "chunks": 5000,
            "total_blocks": 5,
            "by_section": section(0, 15, 0.01),
        },
    )
    result = estimate_from_row(row)
    assert result.chunk_reliable is True
    assert result.density_trusted is False


def test_all_block_types_have_positive_seconds() -> None:
    """上游登记过的方块，破坏时间都必须是正数（硬度 0 的瞬间破坏也算合理，跳过）。"""
    facts = mining_facts.load()
    checked = 0
    for name, info in facts.blocks.items():
        if info.hardness <= 0.0:
            continue
        seconds = facts.break_seconds(name)
        assert seconds > 0, name
        checked += 1
    assert checked > 100, f"只检查了 {checked} 个方块，挖掘事实似乎没读到"


def test_cli_scoring_helpers_resolve_units() -> None:
    """`bg mining` 经 `cli.common._tier` / `_score` 取档位与分数，导入路径写错会直接 ImportError。"""
    from bingo_grading.cli import common

    assert isinstance(common._tier(122.884), int)
    assert isinstance(common._score(122.884), int)
