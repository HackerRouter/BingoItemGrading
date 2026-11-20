"""结构内方块：一趟结构里能拿到多少。"""

from __future__ import annotations


from bingo_grading import gamedata, mining_facts, units
from bingo_grading.case.context import CaseContext, Sourced
from bingo_grading.plan import Action, Requirement
from .bundle import ActionBundle, seconds




def structure_block(
    bundle: ActionBundle,
    ctx: CaseContext,
    *,
    block: str,
    item: str,
    structure: str,
    batch: float,
    action_id: str,
    find_seconds: float = 0.0,
    requires: tuple[Requirement, ...] = (),
    race: str | None = None,
    per_start: float | None = None,
    entries_per_block: float = 1.0,
    capacity: float | None = None,
    travel_per_trip: float = 0.0,
) -> Action | None:
    """只在结构内生成的方块（干草块这类）：进一趟结构能拿到多少。

    `find_seconds` 是「在结构里找到并走到这一堆方块」的每块耗时——
    干草块是亮黄色很好认，但要走过去，所以不能只算破坏时间。

    `per_start` 显式给出「每处几个」时不查 `block_density`——那些只由结构
    放置的方块（红石线、镶金黑石）在方块密度里根本没有行，但
    `structure_content.blocks_per_start` 里有实测值。

    `travel_per_trip` 是**跑一趟结构**的行程成本。第一趟由调用方挂成 `once`
    前置（「走到那里」只付一次），这里只补收**超出一处产能**的那几趟：
    拿 `batch` 个方块要跑 `batch / amount` 趟，超过一趟的部分按趟摊。

    早先把行程记成「每次调用付一趟」再配 `capacity=inf`，等于宣称「一趟
    结构能无限出方块」；反过来按 `batch / amount` 全额摊销又会把第一趟摊成
    零头——`trial_chambers` 每处 5387 个蜡铜块，铜锭因此变成 0.05 TU
    （0.35 秒就能拿到一块铜）。两头都不对，所以拆成「一次 + 超出部分」。
    """
    if per_start is None:
        yield_row = ctx.structure_block_yield(block, structure)
        if yield_row is None:
            bundle.note(f"{block} 缺结构产出统计，这条路线缺席")
            return None
        bundle.record(action_id, yield_row)
        amount = yield_row.value
        source = yield_row.source
    else:
        if per_start <= 0:
            return None
        amount = per_start
        source = "structure_content:blocks_per_start"
        bundle.record(
            action_id,
            Sourced(
                amount * batch,
                source,
                f"{block} 每处 {amount:g} 个（{structure}）",
            ),
        )
    per_block = mining_facts.break_seconds(block or "dirt", fallback="dirt")
    per_block += find_seconds
    # 第一趟由调用方的 `once` 前置支付，这里只补收超出部分：
    # 一处只有 `amount` 个方块，拿 `batch` 个要跑 `batch/amount` 趟。
    extra_trips = max(0.0, (batch / amount if amount > 0 else 0.0) - 1.0)
    return Action(
        action_id=action_id,
        item=item,
        cost=seconds(per_block * batch) + extra_trips * travel_per_trip,
        # 一块方块不一定给一件物品（镶金黑石徒手挖只给 0.35 金粒）。
        yields={item: batch * entries_per_block},
        # `capacity` 是**可调用次数**，不是产出量。默认取「一趟结构里有多少」
        # （同一处不能无限挖），但调用方可传 `inf`——比如末地船龙头平均每处
        # 0.48 个，要拿 1 个得跑两三处，那时行程应该按趟累加而不是把容量
        # 封在 0.48（那会让「拿一个龙头」被直接判为不可行）。
        capacity=(
            capacity
            if capacity is not None
            else (amount / batch if batch > 0 else 0.0)
        ),
        requires=requires,
        label=f"在 {structure} 里挖 {batch:g} 个 {block}",
        source=source,
        race=race,
    )
