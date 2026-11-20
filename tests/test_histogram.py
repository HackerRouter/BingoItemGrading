"""难度直方图：分档清点、维度判定、两种渲染。"""

from __future__ import annotations

from bingo_grading import histogram
from bingo_grading.grade import DifficultyRow
from bingo_grading.plan import Action, ActionSet, Requirement


def _row(item: str, score: int | None, whole: float | None = None) -> DifficultyRow:
    return DifficultyRow(
        item=item,
        score=score,
        tier=None,
        cost_tu=whole,
        whole_cost_tu=whole,
        route="",
        route_label="",
        sources=1,
        uncovered_total=0,
        uncovered_own=0,
        segments=1,
        confidence="high",
    )


def _gate_graph() -> ActionSet:
    """最小的三维图：

    - `stone` 徒手可得 → 主世界
    - `nether_ore` 只能在下界拿（它要求先有下界入口）→ 下界后
    - `elytra` 只能在末地拿 → 末地后
    """
    nether = histogram.NETHER_ACCESS
    the_end = histogram.THE_END_ACCESS
    return ActionSet(
        label="toy",
        actions=(
            Action(action_id="mine:stone", item="cobblestone", cost=1.0, yields={"cobblestone": 1.0}),
            Action(
                action_id="portal",
                item=nether,
                cost=1.0,
                yields={nether: 1.0},
            ),
            Action(
                action_id="kill:blaze",
                item="blaze_rod",
                cost=1.0,
                yields={"blaze_rod": 1.0},
                requires=(Requirement(nether, 1.0),),
            ),
            Action(
                action_id="mine:nether_ore",
                item="nether_ore",
                cost=1.0,
                yields={"nether_ore": 1.0},
                requires=(Requirement(nether, 1.0),),
            ),
            Action(
                action_id="end:portal",
                item=the_end,
                cost=1.0,
                yields={the_end: 1.0},
                requires=(Requirement("ender_eye", 1.0),),
            ),
            Action(
                action_id="craft:ender_eye",
                item="ender_eye",
                cost=1.0,
                yields={"ender_eye": 1.0},
                requires=(Requirement("blaze_rod", 1.0),),
            ),
            Action(
                action_id="loot:end_city",
                item="elytra",
                cost=1.0,
                yields={"elytra": 1.0},
                requires=(Requirement(the_end, 1.0),),
            ),
        ),
    )


def test_classify_splits_by_first_reachable_dimension() -> None:
    """维度按「能不能不用那道门拿到」判定，不是按物品通常在哪出现。"""
    dims = histogram.classify(_gate_graph())
    assert dims["cobblestone"] == histogram.EARTH
    assert dims["nether_ore"] == histogram.NETHER
    # 烈焰棒虽然在下界拿，但它和 nether_access 互为前置 → 判成下界后
    assert dims["blaze_rod"] == histogram.NETHER
    assert dims["elytra"] == histogram.END
    assert dims["ender_eye"] == histogram.NETHER


def test_build_bins_fills_gaps_and_skips_unscored() -> None:
    """空档要补零（否则横轴会缺格），没分数的物品不进图。"""
    dims = {"a": histogram.EARTH, "b": histogram.NETHER, "c": histogram.END}
    rows = [
        _row("a", 0),
        _row("b", 2),
        _row("c", 2),
        _row("d", None),
    ]
    bins = histogram.build_bins(rows, dims)
    assert [item.score for item in bins] == [0, 1, 2]
    assert bins[1].total == 0, "空档补零"
    assert bins[2].counts[histogram.NETHER] == 1
    assert bins[2].counts[histogram.END] == 1
    assert sum(item.total for item in bins) == 3, "无分数的物品被排除"


def test_render_text_marks_the_gate_on_its_bin() -> None:
    """门槛线挂在它的成本所在那档的行尾，不在别的档。"""
    dims = {"a": histogram.EARTH}
    rows = [_row("a", score) for score in range(4)]
    bins = histogram.build_bins(rows, dims)
    meta = histogram.Meta(pack="p", items=4, scored=4)
    # 0.2 TU → 刚好是 score 2 档的中心（0.1 × 2^(2/2)）
    text = histogram.render_text(
        bins, [histogram.Mark(label="下界入口", cost=1.4, color="#000")], meta
    )
    assert text.count("下界入口") == 1, "只挂在一档上"
    marked = next(line for line in text.splitlines() if "下界入口" in line)
    assert marked.lstrip().startswith("2 "), f"挂错了档：{marked}"
    assert "下界入口 1.40 TU" in marked


def test_render_html_is_self_contained() -> None:
    """HTML 不引用外部资源，且把两个维度都画进 SVG。"""
    dims = {"a": histogram.EARTH, "b": histogram.END}
    rows = [_row("a", 1), _row("b", 5)]
    bins = histogram.build_bins(rows, dims)
    meta = histogram.Meta(pack="26.3", items=2, scored=2)
    marks = [
        histogram.Mark(label="下界入口", cost=1.4, color="#7b1f14"),
        histogram.Mark(label="末地入口", cost=2.8, color="#7a5c1f"),
    ]
    page = histogram.render_html(bins, marks, meta)
    assert page.startswith("<!DOCTYPE html>")
    assert 'charset="utf-8"' in page
    assert "<svg" in page
    assert "http://" not in page and "https://" not in page, "不能引用外部资源"
    assert histogram.DIM_COLOR[histogram.EARTH] in page
    assert histogram.DIM_COLOR[histogram.END] in page
    assert "下界入口 1.40 TU" in page, "竖线要带标签"
