"""统一入口：来源索引 → 动作图。

依赖真实统计快照与 `build/26.3/source_index.jsonl`；任一缺失就跳过，
不伪造数据。

断言只看**行为**：任意物品都能拼出动作图、没接上的来源必须上报、
跨表共用一趟行程、配方环被截断而不是爆栈。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bingo_grading.case.context import CaseContext
from bingo_grading.plan import solve
from bingo_grading.sources import actions

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "stats" / "26.3"
INDEX = ROOT / "build" / "26.3" / "source_index.jsonl"

pytestmark = pytest.mark.skipif(
    not SNAPSHOT.exists() or not INDEX.exists(),
    reason=f"缺少快照 {SNAPSHOT} 或来源索引 {INDEX}",
)


@pytest.fixture(scope="module")
def ctx() -> CaseContext:
    return CaseContext.load(SNAPSHOT)


def test_iron_ingot_gets_sources_beyond_mining(ctx: CaseContext) -> None:
    """铁锭不该只有挖矿：箱子与生物掉落都要出现。"""
    built = actions.build(ctx, "minecraft:iron_ingot")
    aset = built.actionset()
    kinds = {
        action.source.split(":")[0]
        for action in aset.by_item().get("minecraft:iron_ingot", [])
    }
    # 箱子来源现在是「跑一趟某结构」，source 写成 `loot_expectation+structure_content:<集合>`。
    assert any(k.startswith("loot_expectation") for k in kinds), "箱子来源没接上"
    assert "mob_density+loot_expectation" in kinds or "structure_content" in {
        a.source.split(":")[0] for a in aset.actions
    }, "生物掉落没接上"
    assert built.records > 20, f"只读到 {built.records} 条来源记录"


def test_iron_ingot_is_cheaper_than_pure_mining(ctx: CaseContext) -> None:
    """接上箱子与掉落之后，铁锭必须明显便宜于「只能挖矿」。"""
    built = actions.build(ctx, "minecraft:iron_ingot")
    solved = solve(built.actionset(), "minecraft:iron_ingot", 1.0)
    assert solved.plan.feasible
    # 手写挖矿口径是 14.9 TU/个；自动拼图不该比它更贵。
    assert solved.plan.cost < 14.0, f"铁锭仍要 {solved.plan.cost:.2f} TU"


def test_loot_sources_share_one_travel_capability(ctx: CaseContext) -> None:
    """同一结构集合的多张表共用一条行程动作，不各付一次。"""
    built = actions.build(ctx, "minecraft:redstone")
    aset = built.actionset()
    travels = [a for a in aset.actions if a.action_id.startswith("travel:")]
    looted = [
        a
        for a in aset.by_item().get("minecraft:redstone", [])
        if a.action_id.startswith("loot:")
    ]
    ids = {action.action_id for action in travels}
    assert len(ids) == len(travels), "行程动作重复了"
    for action in looted:
        caps = [r.item for r in action.requires if r.item.startswith("capability:")]
        assert caps, f"{action.action_id} 没有挂行程前置，相当于免费到达"


def test_uncovered_is_reported_not_silent(ctx: CaseContext) -> None:
    """接不上的来源必须记账。全是 0 才说明真覆盖。"""
    built = actions.build(ctx, "minecraft:iron_ingot")
    assert built.uncovered, "一条都没上报，说明有来源被静默丢掉了"
    reasons = {text.split(":", 1)[0] for text in built.uncovered}
    # 这些是上游真的缺数据，不是接不上：必须如实反映在上报里。
    assert any("缺" in reason for reason in reasons)


def test_recipe_cycle_is_cut(ctx: CaseContext) -> None:
    """红石 ↔ 红石块互为原料，递归必须截断而不是爆栈。"""
    built = actions.build(ctx, "minecraft:redstone")
    assert built.gaps, "配方环没有被记录下来"
    assert any("环" in gap for gap in built.gaps)


def test_dungeon_is_reachable_as_a_feature(ctx: CaseContext) -> None:
    """地牢没有 `structure_density`，入场成本要退回挖矿道搜索。"""
    built = actions.build(ctx, "minecraft:bucket")
    aset = built.actionset()
    # 批量模型下地牢的箱子并进「跑一趟 monster_rooms」。
    looted = [a for a in aset.actions if a.action_id == "loot:monster_rooms"]
    assert looted, "地牢箱子没有进动作图"
    travel = [
        a for a in aset.actions if a.action_id == "travel:minecraft:monster_rooms"
    ]
    assert travel, "地牢行程动作缺失"
    # 搜索代价远大于「走过去」：这 13 TU 级别，不是几十格跑图。
    assert travel[0].cost > 5.0, f"地牢入场只算了 {travel[0].cost:.2f} TU，像是直奔"
    assert travel[0].source == "structure_search"


def test_node_sources_are_wired(ctx: CaseContext) -> None:
    """钓鱼/猪灵/英雄赠礼都以一个节点为前置接进图，不再算「未建模」。"""
    fishing = [
        a for a in actions.build(ctx, "minecraft:bone").actionset().actions
        if a.action_id.startswith("fish:")
    ]
    assert fishing, "钓鱼来源没接上"
    assert any(r.item == "minecraft:fishing_rod" for r in fishing[0].requires)

    barter = [
        a for a in actions.build(ctx, "minecraft:string").actionset().actions
        if a.action_id.startswith("barter:")
    ]
    assert barter, "猪灵交易没接上"
    required = {r.item for r in barter[0].requires}
    assert "capability:nether_access" in required, "猪灵交易没挂「到得了下界」节点"
    assert "minecraft:gold_ingot" in required, "猪灵交易没挂金锭对价"

    gifts = [
        a for a in actions.build(ctx, "minecraft:poppy").actionset().actions
        if a.action_id.startswith("gift:")
    ]
    assert gifts, "英雄赠礼没接上"
    # 这个节点没有来源是**故意的**：袭击胜利尚无建模，路线应因不可达被标出。
    assert any(
        r.item == "capability:hero_of_the_village" for r in gifts[0].requires
    )


def test_pot_table_is_merged_into_structure_trip(ctx: CaseContext) -> None:
    """陶罐表不在来源索引里，但战利品表能查到，会并进「跑一趟 trial_chambers」。"""
    built = actions.build(ctx, "minecraft:arrow")
    trips = [
        a for a in built.actionset().actions if a.action_id == "loot:trial_chambers"
    ]
    assert trips, "trial_chambers 的「跑一趟」动作缺失"
    trip = trips[0]
    # 陶罐表 (`pots/trial_chambers/corridor`) 只在战利品表里，索引没有它。
    # 它被合并进这一趟之后，产出里的箭会明显多于单张箱子表。
    assert trip.yields.get("minecraft:arrow", 0) > 0, "陶罐表的产出没并进来"
    assert "类表" in trip.label, f"没标出合并了几类表：{trip.label}"


def test_hostile_mob_falls_back_to_spawner(ctx: CaseContext) -> None:
    """烈焰人没有自然密度数据，但下界要塞有它的刷怪笼——不能算出 inf。"""
    built = actions.build(ctx, "minecraft:blaze_rod")
    spawners = [
        a for a in built.actionset().actions
        if a.action_id.startswith("spawner:blaze")
    ]
    assert spawners, "烈焰人的刷怪笼来源没接上"
    assert any(
        r.item == "capability:minecraft:nether_complexes"
        for r in spawners[0].requires
    ), "刷怪笼来源没挂下界要塞行程"
    solved = solve(built.actionset(), "minecraft:blaze_rod", 1.0)
    assert solved.plan.feasible, "烈焰棒仍然算不出可行路线"
    assert solved.plan.cost < 700.0


def test_dungeon_depth_split_is_imported(ctx: CaseContext) -> None:
    """C15：地牢按锚点高度拆分，下游要能读到 shallow/deep 两组。"""
    found = ctx.structure_content("minecraft:monster_room", source="measured")
    assert found is not None
    by_depth = found[0].get("by_depth") or {}
    assert set(by_depth) == {"shallow", "deep"}, f"拿到的是 {sorted(by_depth)}"
    for layer in by_depth.values():
        assert layer["count"] > 0
        assert layer["containers_per_dungeon"] > 0


def test_nether_portal_has_two_constructions(ctx: CaseContext) -> None:
    """下界门是两条并列构造：补全废弃传送门 / 从零浇铸，交给引擎比价。"""
    from bingo_grading.sources import constructs

    built = actions.build(ctx, "capability:nether_access")
    solved = solve(built.actionset(), "capability:nether_access", 1.0)
    segment_ids = {
        seg.action_id for seg in solved.curve_of("capability:nether_access").segments
    }
    assert "portal:patch_ruined" in segment_ids, "补全废弃传送门这条没进曲线"
    assert "portal:full_frame" in segment_ids, "从零浇铸这条没进曲线"
    # 补全那条要的比满框少，正是「门框缺口」这件事本身。
    patch = next(c for c in constructs.CONSTRUCTS if c.id == "portal:patch_ruined")
    full = next(c for c in constructs.CONSTRUCTS if c.id == "portal:full_frame")
    patch_obsidian = dict(patch.inputs)["minecraft:obsidian"]
    full_obsidian = dict(full.inputs)["minecraft:obsidian"]
    assert patch_obsidian < full_obsidian, "补全竟然比满框还费黑曜石"


def test_patching_a_ruined_frame_refuses_casting(ctx: CaseContext) -> None:
    """补现成框架只要**现成的黑曜石**，从零垒整框才允许浇铸。

    在已有框架的缺口上精确浇一块，跟挖坑浇一整框不是同一件事：缺口旁边
    就是现成方块，浇下去容易连框一起挡、或凝固在错的位置。所以
    `portal:patch_ruined` 的黑曜石前置带 `forbid=("cast:obsidian",)`。
    """
    built = actions.build(ctx, "capability:nether_access")
    actionset = built.actionset()
    patch = actionset.get("portal:patch_ruined")
    full = actionset.get("portal:full_frame")
    patch_obsidian = next(r for r in patch.requires if r.item == "minecraft:obsidian")
    full_obsidian = next(r for r in full.requires if r.item == "minecraft:obsidian")
    assert patch_obsidian.forbid == ("cast:obsidian",)
    assert full_obsidian.forbid == (), "从零垒整框照样可以浇铸"

    # 黑名单真的生效：把浇筑段从黑曜石曲线里剔掉，
    # 剩下的段里不能再有 cast，而且同一批黑曜石只会更贵（或不可行）
    solved = solve(actionset, "capability:nether_access", 1.0)
    curve = solved.curve_of("minecraft:obsidian")
    assert any(seg.action_id.startswith("cast:obsidian") for seg in curve.segments)
    banned = curve.excluding(*patch_obsidian.forbid)
    assert not any(
        seg.action_id.startswith("cast:obsidian") for seg in banned.segments
    )
    assert len(banned.segments) < len(curve.segments)
    assert banned.cost(patch_obsidian.qty) >= curve.cost(patch_obsidian.qty)


def test_nether_entry_does_not_use_nether_locked_obsidian(ctx: CaseContext) -> None:
    """开门用的黑曜石不能是「下界里挖来的」——那是先有门才拿得到的。

    两条门构造都声明 `forbid_needs=(nether_access,)`：给前置定价时，只要某个
    来源的任一前置落在「不用下界就拿不到」的集合里，这条来源就被剔掉。

    判据必须是不动点而不是静态依赖图：`minecraft:iron_ingot` 的静态前置里有
    `barter:iron_ingot:piglin_bartering`（要下界），但铁锭也能挖矿，所以它不是
    「必须下界」。按静态图判会把铁桶、甚至黑曜石的**全部**来源误禁。
    """
    built = actions.build(ctx, "capability:nether_access")
    actionset = built.actionset()
    solved = solve(actionset, "capability:nether_access", 1.0)
    assert solved.plan.feasible

    # 两条构造都带了自举约束，且作用在黑曜石与点火物上
    for action_id in ("portal:full_frame", "portal:patch_ruined"):
        action = actionset.get(action_id)
        gated = {
            req.item
            for req in action.requires
            if "capability:nether_access" in req.forbid_needs
        }
        assert gated == {"minecraft:obsidian", "capability:igniter"}

    # 下界内部才有的黑曜石来源：必须能识别出来（不动点里属于不可达集）
    from bingo_grading.plan.solve import unreachable_without

    producers: dict[str, list] = {}
    for action in actionset.actions:
        for item in action.yields:
            producers.setdefault(item, []).append(action)
    blocked = unreachable_without("capability:nether_access", producers)
    assert "capability:nether_access" in blocked
    assert "capability:minecraft:nether_complexes" in blocked
    # 铁锭、桶、钻石镐、岩浆都不在其中——它们有主世界来源
    for name in (
        "minecraft:iron_ingot",
        "capability:bucket",
        "minecraft:diamond_pickaxe",
        "minecraft:lava",
    ):
        assert name not in blocked, f"{name} 被误判成「必须下界」"


def test_recipe_self_reference_is_skipped(ctx: CaseContext) -> None:
    """药水「拿一瓶变另一瓶」的配方产出与原料同名，不能生成 A ← A 的动作。"""
    built = actions.build(ctx, "minecraft:potion")
    ids = {a.action_id for a in built.actionset().actions}
    for aid in ids:
        action = next(a for a in built.actionset().actions if a.action_id == aid)
        required = {r.item for r in action.requires}
        assert action.item not in required, f"{aid} 自己要求自己"
    assert any("自引用" in gap for gap in built.gaps), "自引用没有记账"


def test_pot_table_subject_keeps_prefix() -> None:
    """`pots/trial_chambers/corridor` 剥掉前缀就和箱子表撞名，必须保留完整路径。"""
    from bingo_grading.sources import classify

    assert classify._subject_from_table("minecraft:pots/trial_chambers/corridor") == (
        "minecraft:pots/trial_chambers/corridor"
    )
    # 唯一的前缀照旧剥掉，否则会查不到 `loot_expectation`。
    assert classify._subject_from_table("minecraft:chests/desert_pyramid") == (
        "minecraft:desert_pyramid"
    )


def test_trade_alias_expands_smith(ctx: CaseContext) -> None:
    """`smith` 不是独立职业，要展开成 toolsmith / weaponsmith 才能查到报价。"""
    candidates = actions._trade_candidates("smith/2")
    assert "minecraft:toolsmith/2" in candidates
    assert "minecraft:weaponsmith/2" in candidates
    # 铃铛只有 smith/2 这一档有，别名没展开就会报「报价里没有该物品」。
    built = actions.build(ctx, "minecraft:bell")
    trades = [a for a in built.actionset().actions if a.action_id.startswith("trade:")]
    assert trades, "铃铛没有任何交易来源"
    assert not any("报价里没有该物品" in reason for reason in built.uncovered)


def test_wandering_trader_uses_own_capability(ctx: CaseContext) -> None:
    """流浪商人是随机遭遇，不能借用「去趟村庄」的行程。"""
    built = actions.build(ctx, "minecraft:acacia_log")
    wanders = [
        a for a in built.actionset().actions
        if a.action_id.startswith("trade:wandering_trader")
    ]
    assert wanders, "流浪商人报价没进动作图"
    requires = {r.item for r in wanders[0].requires}
    assert actions.WANDERING_TRADER_CAP in requires
    assert "capability:minecraft:villages" not in requires
    # 前置故意无来源：路线应因不可达被标出，而不是被当成免费。
    solved = solve(built.actionset(), "minecraft:acacia_log", 1.0)
    assert all(
        "wandering_trader" not in step.action_id for step in solved.plan.steps
    ), "流浪商人路线不该被当成可达"
