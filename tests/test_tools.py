"""工具链：把工具当目标物品定价，挖矿动作挂 `once` 前置。"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from bingo_grading.case.context import CaseContext
from bingo_grading.case.sources import ActionBundle
from bingo_grading.case.tools import block_is_open, ensure_tool, estimate_cost
from bingo_grading.plan import solve
from bingo_grading.sources import actions

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "stats" / "26.3"
INDEX = ROOT / "build" / "26.3" / "source_index.jsonl"

pytestmark = pytest.mark.skipif(
    not SNAPSHOT.exists(), reason=f"缺少统计快照 {SNAPSHOT}"
)


@pytest.fixture(scope="module")
def ctx() -> CaseContext:
    return CaseContext.load(SNAPSHOT)


@pytest.fixture(scope="module")
def toolchain(ctx: CaseContext) -> ActionBundle:
    """铁镐的工具链：配方 → 木棍 → 木板 → 原木，叶子用采集动作兜底。"""
    bundle = ActionBundle(label="toolchain")
    assert ensure_tool(bundle, ctx, "minecraft:iron_pickaxe")
    return bundle


@pytest.fixture(scope="module")
def toolchain_solved(toolchain: ActionBundle):
    return solve(toolchain.actionset(), "minecraft:iron_pickaxe", 1.0)


@pytest.mark.skipif(not INDEX.exists(), reason=f"缺少来源索引 {INDEX}")
def test_mine_action_carries_the_tool_from_harvest(ctx: CaseContext) -> None:
    """挖矿动作挂工具 `once` 前置：工具由配方链定价，不在动作里写死。"""
    built = actions.build(ctx, "minecraft:raw_gold")
    mine = next(
        action
        for action in built.actionset().actions
        if action.action_id.startswith("mine:") and "gold_ore" in action.action_id
    )
    modes = {req.item: req.mode for req in mine.requires}
    assert modes.get("minecraft:iron_pickaxe") == "once"


def test_tool_chain_is_built_from_recipes(toolchain: ActionBundle) -> None:
    """工具链必须由配方 IR 递归展开出来，不是在案例里手写。"""
    ids = {action.action_id for action in toolchain.actions}
    assert "tool:craft:minecraft:iron_pickaxe" in ids
    assert "tool:craft:minecraft:stick" in ids
    assert "tool:craft:minecraft:oak_planks" in ids
    assert "tool:surface:minecraft:oak_log" in ids


def test_tool_has_a_price(toolchain_solved) -> None:
    """工具作为目标物品走普通曲线，成本必须为正。"""
    cost = toolchain_solved.curve_of("minecraft:iron_pickaxe").cost(1.0)
    assert cost > 0
    # 铁镐 = 3 铁锭 + 2 木棍 + 工序，不能便宜到等于零
    assert cost > 1.0


def test_ingredient_less_recipe_is_flagged(ctx: CaseContext) -> None:
    """`inputs` 为空的配方要标出来，不能静默当成白送。"""
    index, _ = ctx._recipe_index()
    assert index.no_ingredient >= 1


def test_multi_candidate_slot_picks_the_cheaper_chain(toolchain: ActionBundle) -> None:
    """`#minecraft:logs` 里有 `oak_wood`（4 原木 → 3 木），必须选直接采原木。"""
    planks = next(
        a for a in toolchain.actions if a.action_id == "tool:craft:minecraft:oak_planks"
    )
    assert [req.item for req in planks.requires] == ["minecraft:oak_log"]


def test_tool_chain_uses_the_cheapest_recipe(toolchain: ActionBundle) -> None:
    """铁锭有多条配方（熔炼/爆烤/拆块/拆粒），按成本挑，不按文件顺序。"""
    smelt = next(
        a for a in toolchain.actions if a.action_id == "tool:smelt:minecraft:iron_ingot"
    )
    assert [req.item for req in smelt.requires] == ["minecraft:iron_ore"]


def test_cost_estimate_survives_recipe_cycles(ctx: CaseContext) -> None:
    """算铁锭会绕到「烧铁镐得铁粒」再回到铁锭；铁镐不能被记成无解。"""
    cache: dict[str, float] = {}
    ingot = estimate_cost(ctx, "minecraft:iron_ingot", cache=cache)
    pickaxe = estimate_cost(ctx, "minecraft:iron_pickaxe", cache=cache)
    assert math.isfinite(ingot)
    assert math.isfinite(pickaxe)
    assert pickaxe > ingot * 3


def test_expanded_action_ids_are_unique(toolchain: ActionBundle) -> None:
    """同一个物品有多个候选时，动作 ID 必须能区分开。"""
    ids = [action.action_id for action in toolchain.actions]
    assert len(ids) == len(set(ids))


def test_second_best_chain_is_priced_by_the_engine(toolchain_solved) -> None:
    """落选候选也要进动作集，否则「用 oak_wood 更贵」这件事在求解层不存在。"""
    curve = toolchain_solved.curve_of("minecraft:oak_planks")
    prices = {seg.action_id: seg.unit_cost for seg in curve.segments}
    assert "tool:craft:minecraft:oak_planks" in prices
    assert "tool:craft:minecraft:oak_planks~2" in prices
    cheapest = min(prices, key=lambda action_id: prices[action_id])
    assert cheapest == "tool:craft:minecraft:oak_planks"
    # 走 oak_wood（4 原木 → 3 木）必然比直接砍 oak_log 贵：单价由引擎算，不是这里写死
    assert prices["tool:craft:minecraft:oak_planks~2"] > prices[
        "tool:craft:minecraft:oak_planks"
    ]


def test_recipe_cycles_are_not_expanded(toolchain: ActionBundle) -> None:
    """铁粒只能烧铁工具得到、工具又要铁锭——这种环配方不该展开成动作。"""
    ids = {action.action_id for action in toolchain.actions}
    assert not any(i.startswith("tool:smelt:minecraft:iron_nugget") for i in ids)


def test_collect_model_follows_section_fill(ctx: CaseContext) -> None:
    """采集模型按「主段实心占比」判，不靠方块名：竹子长在地表，铁矿埋在地下。"""
    bamboo = ctx.block_openness("minecraft:bamboo")
    iron = ctx.block_openness("minecraft:iron_ore")
    assert bamboo is not None and iron is not None
    assert bamboo[0] < ctx.OPEN_SECTION_FILL
    assert iron[0] > ctx.OPEN_SECTION_FILL
    assert block_is_open(ctx, "minecraft:bamboo")
    assert not block_is_open(ctx, "minecraft:iron_ore")


def test_surface_crops_are_not_priced_as_shafts(ctx: CaseContext) -> None:
    """竹子和原木都在地表，成本应同量级；按矿道算会差 60 倍。"""
    bamboo = estimate_cost(ctx, "minecraft:bamboo")
    log = estimate_cost(ctx, "minecraft:oak_log")
    assert math.isfinite(bamboo)
    assert bamboo < log * 5


def test_missing_section_data_is_not_treated_as_surface(ctx: CaseContext) -> None:
    """没有纵段数据时必须退回矿道模型，不能默认当敞开。"""
    assert ctx.block_openness("minecraft:not_a_real_block") is None
    assert not block_is_open(ctx, "minecraft:not_a_real_block")


def test_block_exposure_splits_sky_and_cave(ctx: CaseContext) -> None:
    """6 面暴露把天空与洞穴拆开——这是判「走过去捡」还是「下洞穴挖」的依据。"""
    bamboo = ctx.block_exposure("minecraft:bamboo")
    clay = ctx.block_exposure("minecraft:clay")
    assert bamboo is not None and clay is not None
    assert bamboo[0].sky > 0.9  # 竹子长在地表
    assert clay[0].sky < 0.01  # 这个包的粘土几乎不露在地表
    assert clay[0].buried > 0.8  # 大头埋在深处
    # 洞穴空气不并进「走过去可得」
    assert bamboo[0].walkable == pytest.approx(bamboo[0].sky + bamboo[0].water)
    assert clay[0].reachable > clay[0].walkable


def test_wet_blocks_still_have_a_surface_source(ctx: CaseContext) -> None:
    """沙子大部分贴水（海底），潜水能捡，地表来源不该被剪掉。"""
    sand = ctx.block_exposure("minecraft:sand")
    assert sand is not None and sand[0].water > 0.3
    assert ctx.surface_block_parts("minecraft:sand") is not None


def test_blocks_without_exposure_get_no_surface_source(ctx: CaseContext) -> None:
    """没有暴露数据的方块不给地表来源：段级数据算不出「它自己露不露」。"""
    assert ctx.block_exposure("minecraft:iron_ore") is None
    assert ctx.surface_block_parts("minecraft:iron_ore") is None


def test_collect_offers_both_surface_and_vein(toolchain: ActionBundle) -> None:
    """同一个方块要两条来源都摆上：地表少量（便宜、带找首片成本）+ 地下大量。"""
    ids = {action.action_id for action in toolchain.actions}
    assert "tool:surface:minecraft:oak_log" in ids
    assert "tool:vein:minecraft:oak_log" in ids


@pytest.mark.skipif(not INDEX.exists(), reason=f"缺少来源索引 {INDEX}")
def test_clay_keeps_surface_and_cave_sources(ctx: CaseContext) -> None:
    """粘土三档：地表（找首片便宜）、洞穴（到达贵但单价低）、矿道（盲挖）。"""
    aset = actions.build(ctx, "minecraft:clay").actionset()
    ids = {action.action_id for action in aset.actions}
    assert {"mine:surface:clay", "mine:cave:clay"} <= ids
    solved = solve(aset, "minecraft:clay", 1.0)
    curve = {seg.action_id for seg in solved.curve_of("minecraft:clay").segments}
    # 前两条都该活下来：小需求量选地表，大需求量会换洞穴
    assert {"mine:surface:clay", "mine:cave:clay"} <= curve
