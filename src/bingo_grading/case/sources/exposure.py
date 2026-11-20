"""按暴露形态取数：洞穴里看得见的、露在地表的。"""

from __future__ import annotations


from bingo_grading.case.context import CaseContext, Sourced
from bingo_grading.plan import Action, Requirement
from .bundle import ActionBundle




def mine_cave(
    bundle: ActionBundle,
    ctx: CaseContext,
    *,
    block: str,
    item: str,
    batch: float,
    action_id: str,
    break_block: str = "dirt",
    find_distance: float | None = None,
    requires: tuple[Requirement, ...] = (),
    race: str | None = None,
) -> Action | None:
    """洞穴暴露的方块：走到洞口、沿洞穴下潜、走过去挖。

    第三种采集模型。地表模型要求方块露在天上/水下，矿道模型要盲挖岩层；
    洞穴里的方块两者都不对——看得见、够得着，但得先下去。

    到达成本进 `overhead`（名字带 `cave:`，与矿道的 `reach:` 不同：
    挖矿道要真的挖竖井，走洞穴不用）。
    """
    parts = ctx.cave_block_parts(
        block, break_block=break_block, find_distance=find_distance
    )
    if parts is None:
        bundle.note(f"{block} 没有洞穴暴露统计，这条路线缺席")
        return None
    per_block, approach, density_source = parts
    bundle.record(
        action_id,
        Sourced(
            per_block.value * batch + approach.value,
            per_block.source,
            f"{block}：到洞穴 {approach.value:.3f} + 每块 {per_block.value:.3f} × {batch:g}",
        ),
    )
    return Action(
        action_id=action_id,
        item=item,
        cost=per_block.value * batch,
        overhead=((f"cave:{block}", approach.value),) if approach.value > 0 else (),
        yields={item: batch},
        requires=requires,
        label=f"下洞穴挖 {batch:g} 个 {block}（{density_source.detail}）",
        source=per_block.source,
        race=race,
    )




def mine_surface(
    bundle: ActionBundle,
    ctx: CaseContext,
    *,
    block: str,
    item: str,
    batch: float,
    action_id: str,
    break_block: str = "dirt",
    find_distance: float | None = None,
    requires: tuple[Requirement, ...] = (),
    race: str | None = None,
) -> Action | None:
    """露头方块（粘土、沙子这类）：看得见，不用挖矿道。

    用「走到能找到够用量的距离 + 挖掉这些方块」——矿道模型会把成本算高一个数量级。

    **找首片是固定成本**，进 `overhead`（带名字，同名只收一次）：密度统计是全图平均，
    它不告诉玩家最近的河在哪，所以这笔钱跑一趟只付一次，不能摊进单价里让
    捡 64 个就付 64 次。与 `mine_vein` 把竖井拆进 `overhead` 同一口径。
    """
    parts = ctx.surface_block_parts(
        block, break_block=break_block, find_distance=find_distance
    )
    if not parts or parts[0] is None:
        bundle.note(f"{block} 没有地表区段的密度，这条路线缺席")
        return None
    per_block, find, density_source = parts
    bundle.record(
        action_id,
        Sourced(
            per_block.value * batch + find.value,
            per_block.source,
            f"{block}：找首片 {find.value:.3f} + 每块 {per_block.value:.3f} × {batch:g}",
        ),
    )
    return Action(
        action_id=action_id,
        item=item,
        cost=per_block.value * batch,
        overhead=((f"find:{block}", find.value),) if find.value > 0 else (),
        yields={item: batch},
        requires=requires,
        label=f"捡 {batch:g} 个 {block}（{density_source.detail}）",
        source=per_block.source,
        race=race,
    )
