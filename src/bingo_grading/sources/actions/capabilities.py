"""能力前置：`capability:*` 怎么造、怎么复用（`once` 去重）。"""

from __future__ import annotations

from bingo_grading import mining_facts
from bingo_grading.case.context import CaseContext, Sourced
from bingo_grading.case.sources import descend_cost
from bingo_grading.mining import surface_y_for
from bingo_grading.plan import Action, Requirement
from bingo_grading.plan.actions import MODE_ONCE
from bingo_grading.sources import constructs as _constructs
from bingo_grading.sources import index as source_index

from .common import DIMENSION_ACCESS, _short, _structure_maps
from .graph import GraphActions




# ---------------------------------------------------------------- 行程


def _ensure_travel(
    record: source_index.SourceRecord,
    ctx: CaseContext,
    result: GraphActions,
    once_caps: set[str],
    structure: str,
) -> str | None:
    """一个结构集合只造一条行程动作，多张表、多个目标共用同一笔。

    `capability:<集合>` 被所有该集合的开箱动作 `once` 前置依赖，
    引擎的 `once` 去重会保证只付一次——跨表、跨目标都算同一趟。
    """
    return _ensure_capability(
        ctx, result, once_caps, structure, route=record.route
    )



def _ensure_capability(
    ctx: CaseContext,
    result: GraphActions,
    once_caps: set[str],
    structure: str,
    *,
    route: str,
) -> str | None:
    """造一个「到达某处」的 `once` 前置（已造过就复用）。

    结构在哪个维度就按哪个维度查间距；跨维度的行程还要先开门——
    那笔钱以 `Requirement` 挂在行程动作上，与其它 `once` 前置同样去重。
    """
    cap = f"capability:{structure}"
    if structure in once_caps:
        return cap
    dimension = ctx.structure_dimension(structure)
    found = ctx.nearest_distance(structure, dimension=dimension)
    access_cost: Sourced | None = None
    if found is not None:
        # 「在地下」有两个来源：来源记录自带的 route，和知识表里的
        # `underground_sets`。「跑一趟」动作没有单条记录可读（route 传空），
        # 只看 route 会把试炼大厅当成地表结构——连 2 倍系数都不加。
        deep = route == "underground" or structure in _structure_maps().underground_sets
        underground = deep or dimension != "minecraft:overworld"
        # 水下结构（海底神殿、海底废墟、沉船、海底废弃传送门）的移动按水下系数。
        # 判定自动：`blocks_per_start` 的水占比超过阈值就是水下，不逐条登记。
        underwater = (
            not deep
            and dimension == "minecraft:overworld"
            and ctx.is_underwater_structure(structure)
        )
        travel = ctx.travel(
            found.value, underground=underground and not underwater, underwater=underwater
        )
        label = (
            f"走到最近一处 {_short(structure)}（{dimension.split(':')[-1]}，"
            f"{found.value:.0f} 格"
            f"{'，水下' if underwater else ('，地下' if underground else '')}）"
        )
        # 地下结构不能「瞬间到达」：`ctx.travel` 只算跑图，还要从地表竖下去。
        # 顶层 y 来自 `knowledge/structure_sets.toml` 的 `[structure_depths]`；
        # 没登记时不假装零成本，而是把「未含竖井」写进假设——偏乐观的路线
        # 必须自己露出来，否则钻石会算成「4 秒一颗」。
        if deep:
            top = _structure_maps().depth_of(structure)
            if top is None:
                result.bundle.note(
                    f"{_short(structure)} 在地下但没登记顶层 y：行程只算了跑图，未含竖井"
                )
            else:
                depth = max(0.0, float(surface_y_for(dimension)) - top)
                if depth > 0:
                    shaft = descend_cost(depth)
                    result.bundle.record(
                        f"shaft:{structure}",
                        Sourced(
                            shaft,
                            "mining:shaft",
                            f"从地表 y{surface_y_for(dimension)} 竖到 y{top:g}：{depth:.0f} 格",
                        ),
                    )
                    travel = Sourced(
                        travel.value + shaft,
                        travel.source,
                        f"{travel.detail} + 竖井 {shaft:.2f}",
                    )
                    label += f"，竖井 {depth:.0f} 格"
    else:
        # 没有结构间距：地牢这类 feature 不在图上标记、地表也看不见，
        # 只能挖矿道碰运气。按体积占比算搜索代价，不能当「知道位置」。
        searched = _search_cost(ctx, structure)
        if searched is None:
            result.uncovered[f"缺结构密度:{structure}"] += 1
            return None
        travel, label = searched, f"挖矿道搜 {_short(structure)}（{searched.detail}）"
    access = DIMENSION_ACCESS.get(dimension)
    requires: tuple[Requirement, ...] = ()
    if access is not None:
        resolved = _ensure_access(ctx, result, once_caps, dimension, access)
        # 开门建模缺失时仍然挂上前置：路线应该因不可达被标出，
        # 而不是因为前置被默默省略而变便宜。
        requires = (Requirement(resolved or access, 1.0, MODE_ONCE),)
    result.bundle.record(f"travel:{structure}", travel)
    result.emit(
        Action(
            action_id=f"travel:{structure}",
            item=cap,
            cost=travel.value,
            yields={cap: 1.0},
            requires=requires,
            label=label,
            source=travel.source,
        )
    )
    once_caps.add(structure)
    return cap



def _search_cost(ctx: CaseContext, structure: str) -> Sourced | None:
    """没有结构间距时的到达代价：挖矿道搜索（体积占比法）。

    每处占地体积优先取实测 `volume_per_start`；地牢没有包围盒，
    体积登记在 `knowledge/structure_sets.toml` 的 `[feature_volumes]`。
    地下高度带取 y≥0：地牢不会生成在深板岩层。
    """
    variants = _structure_maps().members_of(structure)
    volume = _structure_maps().volume_of(structure)
    if volume is None:
        for variant in variants:
            content = ctx.structure_content(variant, source="measured")
            if content and isinstance(content[0].get("volume_per_start"), (int, float)):
                volume = float(content[0]["volume_per_start"])
                break
    if not volume:
        return None
    for variant in variants or (structure,):
        found = ctx.structure_search_cost(
            variant, volume_per_site=volume, bottom_y=0
        )
        if found is not None and found[0] is not None:
            return found[0]
    return None



def _ensure_tool(
    ctx: CaseContext,
    result: GraphActions,
    once_caps: set[str],
    block: str,
) -> tuple[Requirement, ...]:
    """挖这个方块所需的最弱合格工具，作为 `once` 前置。

    `harvest.jsonl` 里的 `minecraft:tool` 组件与 `needs_*_tool` 标签以前
    **只有案例层在用**，而 `bg grade` 读的是这里造的全图动作：四条采集
    来源一条都没挂工具前置，于是黑曜石（要钻石镐）和沙砾（徒手）在价格
    上完全一样——只要跑了传送门，黑曜石就白送。

    工具本身也是普通物品，`result.visit` 会递归展开它的配方链
    （木镐 ← 木板/木棍，石镐 ← 石头，铁镐 ← 铁锭，钻石镐 ← 钻石）。
    这条链按工具等级严格递增，不会成环；`once_caps` 保证每把镐子
    只展开一次，不随方块数量线性膨胀。
    **工具要求是方块属性**，与走哪条采集模型无关：`harvest_tool`（读
    `harvest.jsonl`）只覆盖「战利品表里写了 `match_tool`」的方块——矿石有、
    圆石/深板岩/下界岩没有，于是石头类白送鎬。现在回退到
    `mining_facts.tool_for()`：按 `mineable/*` 与 `needs_*_tool` 标签推导，
    覆盖全部 1286 个方块，且木制工具保证代价链能从原木展开。    """
    found = ctx.harvest_tool(block)
    if found is None:
        tool = mining_facts.tool_for(block)
        if tool is None:
            return ()
    else:
        tool, _detail = found
    if result.visit is not None and tool not in once_caps:
        result.visit(tool, 0)
        once_caps.add(tool)
    return (Requirement(tool, 1.0, MODE_ONCE),)



def _ensure_access(
    ctx: CaseContext,
    result: GraphActions,
    once_caps: set[str],
    dimension: str,
    cap: str,
) -> str | None:
    """跨维度前置：把「开门」当成一个普通目标递归展开。

    `capability:nether_access` 不在来源索引里（它不是物品），但它有
    `constructs` 表声明的两条构造。展开后黑曜石、点燃物各自走自己的
    物品来源链，门框缺口就不再是一个手写的 overhead 常数。
    """
    if cap in once_caps:
        return cap
    if result.visit is None or cap not in _constructs.by_product():
        result.uncovered[f"缺跨维度开门建模:{dimension}"] += 1
        return None
    result.visit(cap, 0)
    once_caps.add(cap)
    return cap
