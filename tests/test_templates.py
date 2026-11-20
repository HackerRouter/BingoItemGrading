"""结构模板的形状匹配：下界门框缺几块（需要 data/ 里的 SNBT 模板）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from bingo_grading import paths
from bingo_grading.templates import (
    FRAME_RING,
    BlockGrid,
    TemplateError,
    load_templates,
    match_portal_frame,
)

TEMPLATES = paths.structure_templates("26.3").path / "ruined_portal"

pytestmark = pytest.mark.skipif(
    not TEMPLATES.is_dir(), reason=f"缺少结构模板 {TEMPLATES}（先跑 bg data sync）"
)


def _grid(ring: str, inner: str = "minecraft:air") -> BlockGrid:
    """合成一个 4×5 的平整框架：外圈全部是 `ring`，内腔全部是 `inner`。"""
    blocks: dict[tuple[int, int, int], str] = {}
    for du, dv in FRAME_RING:
        blocks[(du, dv, 0)] = ring
    for du in range(1, 3):
        for dv in range(1, 4):
            blocks[(du, dv, 0)] = inner
    return BlockGrid(template="synthetic", size=(4, 5, 1), blocks=blocks)


def test_full_obsidian_frame_needs_nothing() -> None:
    match = match_portal_frame(_grid("minecraft:obsidian"))
    assert match is not None
    assert match.have == len(FRAME_RING) == 10
    assert match.missing == 0
    assert match.complete


def test_frame_corners_are_not_required() -> None:
    """四角不需要：去掉四个角、只留上下 2 + 左右 3，仍然是完整的门。"""
    grid = _grid("minecraft:obsidian")
    for corner in ((0, 0), (3, 0), (0, 4), (3, 4)):
        grid.blocks.pop(corner, None)
    match = match_portal_frame(grid)
    assert match is not None
    assert match.have == 10
    assert match.missing == 0


def test_crying_obsidian_is_not_a_frame_block() -> None:
    """哭泣黑曜石不能用来组门框，占着位置也只是缺口。"""
    match = match_portal_frame(_grid("minecraft:crying_obsidian"))
    assert match is not None
    assert match.have == 0
    assert match.missing == 10
    assert match.crying == 10
    assert not match.complete


def test_solid_obsidian_block_is_not_a_portal() -> None:
    """内腔被实心填满时那不是门，是黑曜石堆——站不进去，也谈不上补几块。"""
    assert match_portal_frame(_grid("minecraft:obsidian", inner="minecraft:obsidian")) is None


def test_partial_frame_reports_the_gap() -> None:
    grid = _grid("minecraft:obsidian")
    # 挖掉 5 个必需格子
    for du, dv in list(FRAME_RING)[:5]:
        grid.blocks[(du, dv, 0)] = "minecraft:air"
    match = match_portal_frame(grid)
    assert match is not None
    assert match.have == 5
    assert match.missing == 5


def test_shipped_templates_all_match() -> None:
    grids = load_templates(TEMPLATES)
    assert len(grids) >= 10, "原版废弃传送门有十几种模板"
    for name, grid in sorted(grids.items()):
        match = match_portal_frame(grid)
        assert match is not None, f"{name} 找不到任何像门框的窗口"
        assert 0 <= match.missing <= len(FRAME_RING)
        # 模板里没有哭泣黑曜石，但即使有也只能算缺口
        assert match.have == grid.count("minecraft:obsidian") or match.have <= grid.count(
            "minecraft:obsidian"
        )


def test_template_gap_average_is_partial_not_full() -> None:
    """平均缺口必须严格小于满框——否则说明匹配没起作用。"""
    grids = load_templates(TEMPLATES)
    matches = [
        match
        for match in (match_portal_frame(grid) for grid in grids.values())
        if match is not None
    ]
    average = sum(match.missing for match in matches) / len(matches)
    assert 0.0 < average < len(FRAME_RING)


def test_missing_template_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(TemplateError):
        load_templates(tmp_path / "nope")
