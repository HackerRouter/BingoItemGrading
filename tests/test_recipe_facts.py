"""配方事实接口：折算比例与原料用量都来自 RA 的 `facts/recipe.jsonl`。

这些断言故意直接对上游数据，而不是对案例里的数字：案例改了也要继续成立。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bingo_grading import paths
from bingo_grading.case.context import CaseContext

SNAPSHOT = Path(__file__).resolve().parents[1] / "data" / "stats" / "26.3"
FACTS = paths.recipe_facts("26.3").path

pytestmark = pytest.mark.skipif(
    not SNAPSHOT.exists() or not FACTS.exists(),
    reason=f"缺少统计快照或配方事实（{SNAPSHOT} / {FACTS}）",
)


@pytest.fixture(scope="module")
def ctx() -> CaseContext:
    return CaseContext.load(SNAPSHOT)


def test_nugget_to_ingot_ratio_comes_from_recipe(ctx: CaseContext) -> None:
    found = ctx.recipe_conversion("minecraft:gold_ingot", via="minecraft:gold_nugget")
    assert found is not None
    conversion, layer = found
    assert conversion.amount_of("minecraft:gold_nugget") == pytest.approx(9.0)
    assert conversion.yields == pytest.approx(1.0)
    assert layer.startswith("recipe:")


def test_block_to_ingot_ratio_comes_from_recipe(ctx: CaseContext) -> None:
    conversion, _ = ctx.recipe_conversion("minecraft:gold_ingot", via="minecraft:gold_block")
    assert conversion.yields == pytest.approx(9.0)
    assert conversion.amount_of("minecraft:gold_block") == pytest.approx(1.0)


def test_bucket_needs_three_iron(ctx: CaseContext) -> None:
    """合成不是一比一：桶要 3 铁。"""
    conversion, _ = ctx.recipe_conversion(
        "minecraft:bucket", serializer="minecraft:crafting_"
    )
    assert conversion.inputs == (("minecraft:iron_ingot", 3.0),)
    assert conversion.yields == pytest.approx(1.0)


def test_fire_charge_yields_three_and_takes_one_of_each(ctx: CaseContext) -> None:
    """一次配方出 3 个火焰弹；`coal`/`charcoal` 是二选一，不能两个都收。"""
    conversion, _ = ctx.recipe_conversion(
        "minecraft:fire_charge", serializer="minecraft:crafting_"
    )
    assert conversion.yields == pytest.approx(3.0)
    inputs = dict(conversion.inputs)
    assert inputs == {
        "minecraft:gunpowder": 1.0,
        "minecraft:blaze_powder": 1.0,
        "minecraft:coal": 1.0,
    }


def test_reverse_conversion_needs_via_to_disambiguate(ctx: CaseContext) -> None:
    """小麦能进多条配方；拆干草块必须用 `via` 指认成品，否则会命中面包。"""
    wrong = ctx.recipe_conversion("minecraft:wheat", reverse=True, serializer="minecraft:crafting_")
    assert wrong is not None and wrong[0].inputs[0][0] != "minecraft:hay_block"
    conversion, _ = ctx.recipe_conversion(
        "minecraft:wheat", via="minecraft:hay_block", reverse=True, serializer="minecraft:crafting_"
    )
    assert conversion.yields == pytest.approx(9.0)
    assert conversion.amount_of("minecraft:hay_block") == pytest.approx(1.0)


def test_clay_reverse_conversion(ctx: CaseContext) -> None:
    conversion, _ = ctx.recipe_conversion(
        "minecraft:clay_ball", via="minecraft:clay", reverse=True, serializer="minecraft:crafting_"
    )
    assert conversion.yields == pytest.approx(4.0)
    assert conversion.amount_of("minecraft:clay") == pytest.approx(1.0)


def test_unknown_recipe_returns_none(ctx: CaseContext) -> None:
    """查不到就是查不到：返回 None，让调用方缺席，不给默认值。"""
    assert ctx.recipe_conversion("minecraft:not_a_real_item") is None
    assert ctx.recipe_ratio("minecraft:gold_ingot", "minecraft:diamond") is None
