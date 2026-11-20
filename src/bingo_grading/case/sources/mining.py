"""挖掘：矿脉、竖井分段、二维搜索、紫水晶洞。"""

from __future__ import annotations

import math

from bingo_grading import gamedata, mining_facts, units
from bingo_grading.case.context import CaseContext
from bingo_grading.mining import shaft_cost, surface_y_for
from bingo_grading.plan import Action, Requirement
from .bundle import ActionBundle




def descend_cost(
    depth: float,
    *,
    surface_y: int | None = None,
    block: str = "stone",
    deep_block: str = "deepslate",
) -> float:
    """从地表下潜 `depth` 格：竖井开挖，按岩层分段算。

    地下结构不能「瞬间到达」：`ctx.travel` 只算跑图时间，不含往下挖。
    地牢、矿道这类要从地表竖下去的地方都要加这一段。

    **穿过 y=0 之后围岩是深板岩**（硬度 3.0 对石头 1.5），挖一格的耗时翻倍。
    不分段会把古代城市（y=-51 要走 51 格深板岩）算成跟浅层结构一样便宜。
    口径统一走 `mining.shaft_cost`（含截面）；案例层不重写公式。
    """
    top = surface_y_for() if surface_y is None else surface_y
    bottom = float(top) - abs(depth)
    if bottom >= 0:
        return shaft_cost(
            top, int(bottom), break_seconds=mining_facts.break_seconds(block, material=gamedata.UNDERGROUND_MINING_MATERIAL)
        )
    total = shaft_cost(
        top, 0, break_seconds=mining_facts.break_seconds(block, material=gamedata.UNDERGROUND_MINING_MATERIAL)
    )
    total += shaft_cost(
        0, int(bottom), break_seconds=mining_facts.break_seconds(deep_block, material=gamedata.UNDERGROUND_MINING_MATERIAL)
    )
    return total




# ---------------------------------------------------------------- 挖掘


def mine_vein(
    bundle: ActionBundle,
    ctx: CaseContext,
    *,
    block: str,
    item: str,
    batch: float,
    action_id: str,
    requires: tuple[Requirement, ...] = (),
    entries_per_block: float = 1.0,
    dimension: str | None = None,
    race: str | None = None,
    search_ok: bool = False,
) -> Action | None:
    """散点矿：挖到 `batch` 个目标物品，按密度算出矿道代价。

    `ctx.mining` 已经把「一块方块掉 `entries_per_block` 个」折进代价里了——
    它内部先算 `blocks_needed = batch / entries_per_block` 再估矿道长度。
    所以这里的产出就是 `batch` 个物品，不能再乘一遍 `entries_per_block`。
    """
    estimate, sourced = ctx.mining(
        block,
        target_items=batch,
        entries_per_block=entries_per_block,
        dimension=dimension,
    )
    if estimate is None or estimate.best is None or sourced is None:
        bundle.note(f"{block} 没有可用的密度统计，这条路线缺席")
        return None
    # 二维搜索模型只用于**不埋在地下**的方块。判据直接用 `record.route`——
    # 它是 `block_exposure` 的 6 面实测判出来的（贴天空/水过半 → 地表），
    # 没有暴露数据的方块退回 `knowledge/routes.toml`。不需要另加几何判据：
    # 实测 `bee_nest` / `cactus_flower` / `chorus_flower` 的 route 分别是
    # surface / surface / other_dimension，而 `skeleton_skull` 是 underground
    # （远古城市在 y-51），分得很准。
    #
    # 这类方块的正确模型是**二维搜索**（与 `block_search_cost` /
    # `biome_search_cost` 同一口径）：`距离 ≈ ½·√(256 ÷ ρ)`，而不是
    # 「必须挖穿 `1/ρ` 块岩层才碰到一块」。否则蜂巢（ρ=0.0048/区块）会算出
    # 111456 TU，而同一处取蜜只要 4.85 TU——两条模型差四个数量级。
    if search_ok:
        return _search_blocks(
            bundle,
            block=block,
            item=item,
            batch=batch,
            action_id=action_id,
            per_chunk=section_per_chunk(estimate),
            break_block=section_break_block(estimate),
            entries_per_block=entries_per_block,
            requires=requires,
            race=race,
            dimension=dimension or ctx.dimension,
        )
    if not estimate.density_trusted:
        # 样本太少又埋在地下：既不该按 `1/ρ` 外推，也不该按二维搜索。
        # 不做散点矿，交给 `_structure_placed()` 兜底——骷髅头方块全图只
        # 数到 33 块（就是远古城市那 3 个/处），正确的算法是「跑一趟去挖」，
        # 而不是「挖穿 1560406 TU 的岩层」。
        bundle.note(
            f"{block} 只数到 {estimate.sample_blocks} 块且在地下，不做散点矿"
        )
        return None
    bundle.record(action_id, sourced)
    section = estimate.best
    # 竖井是「到达这一层」的一次性投入，不是每批都要重挖：从单价里拆出来，
    # 进动作自带的固定成本（带名字，同层同维度的两笔只收一次）。
    total = sourced.value
    shaft = min(section.shaft_tu, total)
    local = max(0.0, total - shaft)
    reach = (
        f"reach:{dimension or ctx.dimension}:{section.y_range[0]}-{section.y_range[1]}"
    )
    return Action(
        action_id=action_id,
        item=item,
        cost=local,
        overhead=((reach, shaft),) if shaft > 0 else (),
        yields={item: batch},
        requires=requires,
        label=f"挖 {batch:g} 个 {block}（{estimate.biome} y{section.y_range[0]}~{section.y_range[1]}）",
        source=sourced.source,
        race=race,
    )




def section_per_chunk(estimate) -> float:
    """最优纵段的「每区块方块数」。"""
    best = estimate.best
    return float(best.per_chunk_density) if best is not None else 0.0




def section_break_block(estimate) -> str:
    """最优纵段的围岩类型（决定破坏秒数）。"""
    best = estimate.best
    return best.break_block if best is not None else "stone"




def _search_blocks(
    bundle: ActionBundle,
    *,
    block: str,
    item: str,
    batch: float,
    action_id: str,
    per_chunk: float,
    break_block: str,
    entries_per_block: float,
    requires: tuple[Requirement, ...],
    race: str | None,
    dimension: str,
) -> Action | None:
    """稀疏方块的二维搜索模型：找得到就走过去挖，不用挖穿岩层。

    `距离 ≈ ½·√(256 × N ÷ ρ)`（N 是要破的方块数、ρ 是每区块方块数）。
    与 `block_search_cost` / `biome_search_cost` 同一口径——那个常数不是拟合
    出来的，是「二维平面里最近的若干点」的期望距离。

    `entries_per_block` 不能省：撑叶只有 0.5% 概率掉苹果，要拿 1 个苹果就得
    破 200 个撑叶。早先这里只乘了 `batch`（=1 件物品），于是苹果、树苗、
    小麦种子这类「方块多、掉率低」的产物全被算成 0.09 TU——比跑到村庄
    去拿（7 TU） 便宜三个数量级。

    `dimension` 只用于标签；跨维度前置由调用方的 `requires` 负责。
    """
    if per_chunk <= 0:
        bundle.note(f"{block} 密度为零，二维搜索也没有意义")
        return None
    blocks = batch / entries_per_block if entries_per_block > 0 else batch
    distance = 0.5 * math.sqrt(256.0 * blocks / per_chunk)
    break_seconds = mining_facts.break_seconds(
        break_block or "stone",
        material=gamedata.UNDERGROUND_MINING_MATERIAL,
        fallback="stone",
    )
    cost = distance * units.TU_PER_BLOCK_RUN + blocks * break_seconds / units.SECONDS_PER_TU
    bundle.note(
        f"{block} 样本不足，按二维搜索计：每 {1.0 / per_chunk:.0f} 区块一处，"
        f"找 {blocks:g} 块走 {distance:.0f} 格"
    )
    return Action(
        action_id=action_id,
        item=item,
        cost=cost,
        yields={item: batch},
        requires=requires,
        label=(
            f"找 {block} 挖 {blocks:g} 块出 {batch:g} 个"
            f"（每 {1.0 / per_chunk:.0f} 区块一处，走 {distance:.0f} 格 + "
            f"挖 {break_seconds:.1f}s×{blocks:g}）"
        ),
        source="block_density:search",
        race=race,
    )




def mine_geode(
    bundle: ActionBundle,
    ctx: CaseContext,
    *,
    item: str,
    action_id: str,
    probe_block: str = "minecraft:amethyst_block",
    requires: tuple[Requirement, ...] = (),
    dimension: str | None = None,
) -> Action | None:
    """紫水晶洞：挖到第一块洞壁就算找到整窝，一次采走。

    与 `mine_vein` 的差别只有一句：**不按 `1/ρ` 线性外推**。
    散点矿挖穿岩层要平均挖 `1/ρ` 块才碰到一块；但紫水晶洞是球形空腔，
    碰到任意一块洞壁就意味着整窝的成熟簇都在手边。

    所以成本 = 「挖穿岩层碰到第一块洞壁」，收益 = 一整洞的成熟簇
    （由 `ctx.geode_harvest()` 按实测密度算，见那里的推导）。
    """
    harvest = ctx.geode_harvest(dimension=dimension)
    if harvest is None:
        bundle.note("缺紫水晶簇与 budding 的密度统计，紫水晶洞这条路线缺席")
        return None
    shards, detail = harvest
    estimate, sourced = ctx.mining(
        probe_block,
        target_items=1.0,
        entries_per_block=1.0,
        dimension=dimension,
    )
    if estimate is None or estimate.best is None or sourced is None:
        bundle.note(f"{probe_block} 没有可用的密度统计，紫水晶洞这条路线缺席")
        return None
    bundle.record(action_id, sourced)
    section = estimate.best
    # 竖井同 `mine_vein`：到达这一层的一次性投入，拆进 `overhead`。
    total = sourced.value
    shaft = min(section.shaft_tu, total)
    local = max(0.0, total - shaft)
    reach = (
        f"reach:{dimension or ctx.dimension}:{section.y_range[0]}-{section.y_range[1]}"
    )
    return Action(
        action_id=action_id,
        item=item,
        cost=local,
        overhead=((reach, shaft),) if shaft > 0 else (),
        yields={item: shards.value},
        requires=requires,
        label=(
            f"挖穿岩层碰到一处紫水晶洞、把成熟簇采走"
            f"（y{section.y_range[0]}~{section.y_range[1]}，{detail}）"
        ),
        source="block_density:geode",
    )
