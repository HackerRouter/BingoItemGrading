"""开箱：跑一趟结构把箱子开掉。"""

from __future__ import annotations


from bingo_grading import gamedata
from bingo_grading.case.context import CaseContext
from bingo_grading.plan import Action, Requirement
from .bundle import ActionBundle, seconds




# ---------------------------------------------------------------- 开箱


def loot_site(
    bundle: ActionBundle,
    ctx: CaseContext,
    *,
    subject: str,
    structure: str,
    chests_per_site: float,
    action_id: str,
    primary: str | None = None,
    equivalents: dict[str, float] | None = None,
    requires: tuple[Requirement, ...] = (),
    condition: str = "tools=present",
    underground_share: float = 0.0,
    with_travel: bool = True,
    travel_cost: float | None = None,
    race: str | None = None,
    dimension: str | None = None,
    open_containers: float | None = None,
) -> Action | None:
    """跑一趟结构，开掉里面的箱子。

    `chests_per_site` 是「这张表每处出现几次」（宝藏箱 0.1、`bastion_other` 6.1），
    `open_containers` 是「一趟要开几个箱」（容器总数 7.2）。两个不一样：

    - **产出**只看这张表：`per_chest × chests_per_site`；
    - **开箱时间**按全部容器算：一趟必然把箱子都开掉（顺带的也算看了）。

    若两者混用，拿总数乘一张表的期望会把「一趟能拿到多少」放大几十倍；
    反过来只拿该表的箱数算开箱时间，会少算「绕过去开其它箱」的功夫。

    产出写成**整份**每箱期望（不折算成目标物品）：引擎会自己用
    「金粒 → 金锭」这类转换动作折算，不需要案例层预先加权。

    `underground_share` 是「这个结构有多少比例生成在地下」，用来把
    地表与地下两种旅行代价按比例混合。

    `with_travel=False` 表示「到达这个结构」的成本由调用方另外用
    `capability` 单独付（每趟一次）。
    `travel_cost` 显式给出到达成本——给那些没有 `structure_density` 的结构用
    （地牢这类 feature，距离得从采样密度推，还要加上竖井下潜）。
    """
    per_chest = ctx.loot_per_chest_all(
        subject, condition=condition, dimension=dimension
    )
    if per_chest is None:
        bundle.note(f"缺 {subject} 的战利品期望，这条路线缺席")
        return None
    table, detail = per_chest
    yields = {
        item: amount * chests_per_site
        for item, amount in table.items()
        if amount > 0
    }
    if not yields:
        bundle.note(f"{subject} 的箱内产出为空，这条路线缺席")
        return None

    # `with_travel=False` 时行程由调用方用 `capability:` 单独付，
    # 这里不能再查一次结构密度——那个查询只认主世界，会让下界结构
    # 被误判成「没有数据」。
    if with_travel:
        travel = (
            _site_travel(ctx, structure, underground_share=underground_share)
            if travel_cost is None
            else travel_cost
        )
        if travel is None:
            bundle.note(f"缺 {structure} 的结构密度，这条路线缺席")
            return None
    else:
        travel = 0.0
    opened = chests_per_site if open_containers is None else open_containers
    cost = seconds(gamedata.CHEST_SECONDS) * opened
    if with_travel:
        cost += travel
    label = f"跑一趟 {structure}（开 {opened:g} 个箱，其中 {chests_per_site:g} 个是这张表）"
    if opened <= 0 or chests_per_site <= 0:
        label = f"跑一趟 {structure}"
    return Action(
        action_id=action_id,
        item=primary or max(yields, key=lambda name: yields[name]),
        cost=cost,
        yields=yields,
        equivalents=dict(equivalents or {}),
        requires=requires,
        label=label,
        source=f"loot_expectation:{subject}",
        race=race,
    )




def _site_travel(
    ctx: CaseContext, structure: str, *, underground_share: float
) -> float | None:
    found = ctx.nearest_distance(structure)
    if found is None:
        return None
    # 水下结构（沉船、海底神殿、海底废墟）游泳只有步行的一半速度。以前这里
    # 一律按地表算，到达成本被低估一半——`structure_water_share()` 早就把这个
    # 判断做出来了（按实例数加权的体积水占比），不需要新数据。
    underwater = ctx.is_underwater_structure(structure)
    surface = ctx.travel(found.value, underground=False, underwater=underwater).value
    if underground_share <= 0:
        return surface
    under = ctx.travel(found.value, underground=True).value
    return surface * (1 - underground_share) + under * underground_share
