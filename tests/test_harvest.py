"""RA 导出的 `harvest.jsonl`：方块 → 最低工具等级 / 最弱合格工具。

这层是「挖矿要什么工具」的唯一出处：下游不读标签，也不从工具组件反推。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bingo_grading import paths
from bingo_grading.case.context import CaseContext

SNAPSHOT = Path(__file__).resolve().parents[1] / "data" / "stats" / "26.3"
HARVEST = paths.harvest_facts("26.3")

pytestmark = pytest.mark.skipif(
    not SNAPSHOT.exists() or not HARVEST.exists,
    reason=f"缺少统计快照或 harvest 产物（{SNAPSHOT} / {HARVEST.path}）",
)


@pytest.fixture(scope="module")
def ctx() -> CaseContext:
    return CaseContext.load(SNAPSHOT)


def test_gold_ore_needs_iron_pickaxe(ctx: CaseContext) -> None:
    found = ctx.harvest_tool("minecraft:gold_ore")
    assert found is not None
    tool, detail = found
    assert tool == "minecraft:iron_pickaxe"
    assert ctx.harvest_level("minecraft:gold_ore") == "iron"
    assert "iron" in detail


def test_redstone_ore_needs_iron_pickaxe(ctx: CaseContext) -> None:
    assert ctx.harvest_level("minecraft:redstone_ore") == "iron"
    assert ctx.harvest_tool("minecraft:deepslate_redstone_ore")[0] == "minecraft:iron_pickaxe"


def test_diamond_ore_level_is_iron_not_diamond(ctx: CaseContext) -> None:
    """原版钻石矿用铁镐即可；这条挡住「按名字给等级」那种想当然。"""
    assert ctx.harvest_level("minecraft:diamond_ore") == "iron"


def test_obsidian_needs_diamond_pickaxe(ctx: CaseContext) -> None:
    found = ctx.harvest_tool("minecraft:obsidian")
    assert found is not None
    assert found[0] == "minecraft:diamond_pickaxe"


def test_soft_blocks_have_no_requirement(ctx: CaseContext) -> None:
    """RA 的约定：不在 needs_* 里的方块不报工具要求（宁可少报）。"""
    assert ctx.harvest_tool("minecraft:dirt") is None
    assert ctx.harvest_tool("minecraft:stone") is None


def test_every_row_is_well_formed() -> None:
    rows = [
        json.loads(line)
        for line in HARVEST.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows
    for row in rows:
        assert isinstance(row["block"], str)
        assert row["tool_level"] in {"stone", "iron", "diamond"} or row["tool_level"] is None
        assert isinstance(row["tools"], list)
        assert isinstance(row["gap"], bool)
    assert not [row for row in rows if row["gap"]], "有等级要求却推不出工具，是缺口"
