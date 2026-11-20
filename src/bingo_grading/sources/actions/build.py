"""编排入口：`build()` 把来源记录翻译成动作图。"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence
from bingo_grading import gamedata
from bingo_grading.case.context import CaseContext
from bingo_grading.case.sources import ActionBundle, craft, seconds, smelt
from bingo_grading.plan import Action, Requirement
from bingo_grading.plan.actions import MODE_ONCE, MODE_PER_USE
from bingo_grading.recipes import facts
from bingo_grading.sources import constructs as _constructs
from bingo_grading.sources import index as source_index

from .blocks import _block, _sweep_tables
from .common import MAX_DEPTH, SMELT_SERIALIZERS, _short, default_index
from .graph import GraphActions
from .loot import _loot, _suspicious
from .mobs import _mob, _shear
from .structures import _structure_batches
from .trade import _trade
from .transmute import _placeholder_variants, _transform_sources




def build(
    ctx: CaseContext,
    target: str,
    *,
    pack: str | None = None,
    index_path: Path | None = None,
    max_depth: int = MAX_DEPTH,
    extra_targets: Sequence[str] = (),
    progress: Callable[[int, int, str], None] | None = None,
) -> GraphActions:
    """从来源索引自动拼出 `target` 的动作图（递归补齐原料与工具）。

    `extra_targets` 让一次构建覆盖多个目标：`visit` 里的 `depth_of` 会把
    共享的前置链只展开一次（以最浅深度为准），所以全库联合构建的成本远低于
    逐件 build。
    每件的图本来就包含它整条配方链（单件就有 356 个动作），逐件构建等于
    把那 356 个动作反复重复一遍。

    `progress` 在每展开完一个目标后回调 `(已完成, 总数, 刚展开的目标)`，
    供调用方画进度条。真正耗时的是后面的求解与逐件取价，所以这个回调
    只覆盖「建图」这一段。
    """
    pack = pack or ctx.pack_version()
    header, records = source_index.read(index_path or default_index(pack))
    by_item: dict[str, list[source_index.SourceRecord]] = {}
    for record in records:
        by_item.setdefault(record.item, []).append(record)

    count = 1 + len(extra_targets)
    label = f"auto:{target}" if count == 1 else f"auto:all({count})"
    result = GraphActions(label=label, bundle=ActionBundle(label=label))
    result.bundle.note(
        f"来源索引 {header.get('label')}：{header.get('item_count')} 个物品、"
        f"{header.get('source_count')} 条来源"
    )
    visiting: list[str] = []
    # 已展开过的**最小深度**。用 set 记录「展开过没有」会让结果依赖遍历顺序：
    # 联合构建时一个物品常常先作为别的目标的配方输入被访问（depth>0），
    # 等它自己当目标（depth=0）时被跳过，于是它自己的来源没展开。
    # 实测 `copper_block` 因此从单件 6.65 TU 变成全库 20.09 TU。
    depth_of: dict[str, int] = {}
    once_caps: set[str] = set()

    def visit(item: str, depth: int) -> None:
        if item in visiting:
            result.gaps.append(f"{item}：配方环，已在当前链上，不再展开")
            return
        if depth > max_depth:
            result.gaps.append(f"{item}：递归超过 {max_depth} 层，未展开")
            return
        if depth_of.get(item, max_depth + 1) <= depth:
            return
        visiting.append(item)
        try:
            # 1. 构造（`capability:` 不是物品，索引里没有它）
            for construct in _constructs.by_product().get(item, ()):
                _emit_construct(construct, ctx, result, visit, depth)
            # 2. 索引里的直接来源
            for record in by_item.get(item, ()):
                result.recorded[record.item] += 1
                covered_by_roadtrip = (
                    record.structure_set is not None
                    and record.structure_set in result.batched_structures
                )
                before_actions = len(result.bundle.actions)
                before_gaps = len(result.gaps)
                before_uncovered = sum(result.uncovered.values())
                action = _from_record(record, ctx, result, pack, once_caps)
                if (
                    action is None
                    and not covered_by_roadtrip
                    and len(result.bundle.actions) == before_actions
                    and len(result.gaps) == before_gaps
                    and sum(result.uncovered.values()) == before_uncovered
                ):
                    # 既不产动作、也不记账：账本上会凭空少一条来源。
                    result.uncovered[
                        f"静默丢弃:{record.source_type}:{_short(record.item)}"
                    ] += 1
                result.records += 1
                result.by_type[record.source_type] += 1
                result.emit(action)
            # 3. 配方与熔炼
            conversions, layer = ctx.recipe_conversions(item, pack=pack)
            for position, conversion in enumerate(conversions):
                action = _from_conversion(
                    conversion, ctx, result, layer, position, pack
                )
                result.emit(action)
                for name, _ in conversion.inputs:
                    visit(name, depth + 1)
            # 4. 成片资源的浇铸/转换（黑曜石要这一条）
            _transform_sources(item, ctx, result, once_caps, depth)
        finally:
            visiting.pop()
            depth_of[item] = min(depth_of.get(item, depth), depth)

    result.visit = visit
    result.once_caps = once_caps
    # 每个结构集合造一条「跑一趟」的动作：一趟把该处所有箱子都开掉，
    # 收益合并。跑第二趟就再付一次行程——这正是「去下一个要累加代价」。
    batched = _structure_batches(ctx, result, once_caps)
    result.batched_structures = batched
    targets = (target, *extra_targets)
    for index, name in enumerate(targets, 1):
        visit(name, 0)
        if progress is not None:
            progress(index, len(targets), name)
    # 方块变换的原料：主链展开完再补，顺序扰动不会传进主链。
    # 补进来的那次 visit 可能又发现新的变换原料，所以循环到不再新增。
    pending = sorted(result.transmute_needs)
    while pending:
        for name in pending:
            visit(name, 0)
        result.transmute_needs.difference_update(pending)
        pending = sorted(result.transmute_needs)
    _sweep_tables(ctx, result, depth_of, once_caps)
    # 补齐：被别的动作当费用、但图里没人产出的物品。
    #
    # 有些物品**只在配方里存在**：配方不算来源，所以来源索引里没有它们的行，
    # 只有当别的动作把它们当费用时才被提到。交易是典型——渔夫用金合欢船换
    # 绿宝石，`acacia_boat` 因此成了前置，但交易动作只写 `Requirement`、不展开它，
    # 于是它永远没有动作，分层把整条交易判成 `no_rule` 丢掉。
    #
    # 不能在第 2 步里直接 visit 交易的 wants：那会把「谁被谁当费用」的传递闭包
    # 全展开一遍（实测 pytest 跑不完）。这里只补**确实缺口**的那几个，数量极小。
    # 限轮数是因为 `visit` 只认更浅的深度，理论上补完就收敛，但不愿依赖这一点。
    for _round in range(3):
        result.settle_prereqs()
        missing = sorted(result.missing_prereqs)
        if not missing:
            break
        for name in missing:
            visit(name, 0)
    result.settle_coverage()
    result.settle_prereqs()
    return result



# ---------------------------------------------------------------- 构造


def _emit_construct(
    construct: _constructs.Construct,
    ctx: CaseContext,
    result: GraphActions,
    visit: Callable[[str, int], None],
    depth: int,
) -> None:
    """展开一条构造：占位符输入按岩浆段展开，普通输入递归定价。"""
    placeholders = [
        (name, qty)
        for name, qty in construct.inputs
        if _constructs.placeholder_prefix(name) is not None
    ]
    fixed = [
        (name, qty)
        for name, qty in construct.inputs
        if _constructs.placeholder_prefix(name) is None
    ]
    # 普通输入先递归，让它们自己的来源出生。
    for name, _qty in fixed:
        visit(name, depth + 1)

    if not placeholders:
        requires = tuple(
            Requirement(
                name,
                qty,
                MODE_PER_USE,
                forbid=construct.forbid_for(name),
                forbid_needs=construct.forbid_needs_for(name),
            )
            for name, qty in fixed
        )
        result.emit(
            Action(
                action_id=construct.id,
                item=construct.product,
                cost=seconds(construct.seconds),
                yields={construct.product: construct.amount},
                requires=requires,
                label=construct.label,
                source=construct.source,
            )
        )
        return

    # 占位符逐个展开：每段岩浆湖一条来源，互不替换（浅段便宜但稀）。
    for name, _qty in placeholders:
        prefix = _constructs.placeholder_prefix(name) or name
        variants = _placeholder_variants(prefix, ctx, result)
        if not variants:
            result.uncovered[f"缺成片资源:{prefix}"] += 1
            continue
        for variant, extra_requires in variants:
            requires = [
                Requirement(variant, 1.0, MODE_ONCE),
                *(
                    Requirement(
                        n,
                        q,
                        MODE_PER_USE,
                        forbid=construct.forbid_for(n),
                        forbid_needs=construct.forbid_needs_for(n),
                    )
                    for n, q in fixed
                ),
            ]
            requires.extend(extra_requires)
            result.emit(
                Action(
                    action_id=f"{construct.id}@{_short(variant)}",
                    item=construct.product,
                    cost=seconds(construct.seconds),
                    yields={construct.product: construct.amount},
                    requires=tuple(requires),
                    label=f"{construct.label}（{variant.split(':')[-1]}）",
                    source=construct.source,
                )
            )



# ---------------------------------------------------------------- 分派


def _convert(
    record: source_index.SourceRecord,
    ctx: CaseContext,
    result: GraphActions,
    pack: str,
    once_caps: set[str],
) -> Action | None:
    """手持物品用一下就变成另一个物品：`map` → `filled_map`、`writable_book` → `written_book`。

    来自 `bridge/item_conversion`（`kind=transmutes`，`actor=assume:player`）。
    它不是合成台配方，也没有战利品表：右键使用当场换物品，**不需要走到未记录
    区块去填图**（空地图右键即生成已填充地图），所以成本只有一次右键，不叠行程。

    输入物品被消耗（变成产物），所以是 `per_use` 而不是 `once`。
    """
    source_item = record.subject
    if not source_item or not source_item.startswith("minecraft:"):
        # 拿不到输入物品就不猜方向：宁可不给路线，也不编一个「凭空变」的动作。
        result.uncovered[f"缺转换输入:{record.item}"] += 1
        return None
    result.visit(source_item, 0)
    return Action(
        action_id=f"convert:{_short(record.item)}:{_short(source_item)}",
        item=record.item,
        cost=seconds(gamedata.ITEM_CONVERT_SECONDS),
        yields={record.item: 1.0},
        requires=(Requirement(source_item, 1.0, MODE_PER_USE),),
        label=(
            f"拿 {_short(source_item)} 用一下变成 {_short(record.item)}："
            f"右键 {gamedata.ITEM_CONVERT_SECONDS:g}s"
        ),
        source="bridge/item_conversion",
    )



def _fill(
    record: source_index.SourceRecord,
    ctx: CaseContext,
    result: GraphActions,
    pack: str,
    once_caps: set[str],
) -> Action | None:
    """拿空容器装流体/半流体：空桶 + 目标 → 满桶（水桶 / 细雪桶）。

    上游把这一族登记成 `block_drop`（「挖了掉自己」），但水、岩浆、细雪**都挖不下来**：
    水与岩浆压根没有掉落，细雪方块被破坏时什么都不掉。三者都只能用空桶右键装，
    所以成本 = 找到那一处流体/方块 + 一次右键，前置是空桶（被消耗）。

    按旧口径算出来的水桶是 0.41 TU、细雪桶 1.53 TU——比空桶本身还便宜，
    因为那条路只算了「挖一个方块」。
    """
    block = record.subject
    containers = [
        note.split(":", 1)[1]
        for note in record.notes or ()
        if note.startswith("item:")
    ]
    container = containers[0] if containers else "minecraft:bucket"
    if block == "minecraft:lava":
        # 岩浆湖那条已有专门构造（`bucket:lava_bucket`：岩浆湖段位 + 倒桶）。
        # 这里再给一条粗估只会把「挖岩浆」的假路线换成另一个粗估。
        result.uncovered[f"装岩浆交给构造:{record.item}"] += 1
        return None
    if block == "minecraft:water":
        water = ctx.water_search_cost()
        if water is None:
            result.uncovered[f"装桶缺水体定位:{block}"] += 1
            return None
        travel, biome = water
        detail = f"走到最近水域（{biome.split(':')[-1]}）"
    else:
        found = ctx.block_search_cost(block)
        if found is None:
            result.uncovered[f"装桶缺方块定位:{block}"] += 1
            return None
        travel, detail = found
    result.visit(container, 0)
    return Action(
        action_id=f"fill:{_short(record.item)}:{_short(block)}",
        item=record.item,
        cost=travel.value + seconds(gamedata.PLACE_SECONDS),
        yields={record.item: 1.0},
        # 空桶被装成满桶，所以是 per_use 而不是 once。
        requires=(Requirement(container, 1.0, MODE_PER_USE),),
        label=(
            f"拿 {_short(container)} 装 {_short(block)}：{detail}，"
            f"右键一下（{gamedata.PLACE_SECONDS:g}s）"
        ),
        source=f"code/fluid_buckets:{block}",
    )



def _from_record(
    record: source_index.SourceRecord,
    ctx: CaseContext,
    result: GraphActions,
    pack: str,
    once_caps: set[str],
) -> Action | None:
    """一条来源记录 → 一个动作。接不上就记账，不返回半成品。"""
    handler = _HANDLERS.get(record.source_type)
    if handler is None:
        result.uncovered[f"未接入的来源类型:{record.source_type}"] += 1
        return None
    return handler(record, ctx, result, pack, once_caps)



_HANDLERS = {
    "loot_table": _loot,
    "suspicious_block": _suspicious,
    "mob_drop": _mob,
    "block_drop": _block,
    "shear": _shear,
    "trade": _trade,
    "convert": _convert,
    "fill": _fill,
}



# ---------------------------------------------------------------- 配方链


def _from_conversion(
    conversion: facts.Conversion,
    ctx: CaseContext,
    result: GraphActions,
    layer: str,
    position: int,
    pack: str,
) -> Action | None:
    """一条配方折算 → 一个动作（熔炼带时间，组装只花手工）。"""
    inputs = dict(conversion.inputs)
    if not inputs:
        result.uncovered[f"配方无原料:{conversion.output}"] += 1
        return None
    # 药水这类「拿一瓶药水加材料变另一瓶」的配方，产出与原料同名。
    # 照抄会生出一条 `A ← A` 的动作，求解器直接判自相矛盾；跳过并记账。
    if conversion.output in inputs:
        result.gaps.append(
            f"{conversion.output}：配方自引用（{conversion.detail}），已跳过"
        )
        return None
    yields = {conversion.output: float(conversion.yields)}
    if conversion.serializer in SMELT_SERIALIZERS and len(inputs) == 1:
        raw = next(iter(inputs))
        action = smelt(
            result.bundle,
            ctx,
            item=conversion.output,
            raw=raw,
            batch=float(conversion.yields),
            action_id=f"smelt:{_short(conversion.output)}#{position}",
        )
        return action
    return craft(
        result.bundle,
        action_id=f"craft:{_short(conversion.output)}#{position}",
        yields=yields,
        inputs=inputs,
        cost=seconds(gamedata.CRAFT_SECONDS_PER_STEP),
        label=f"合成 {_short(conversion.output)}（{conversion.detail}）",
        source=layer or "recipe",
    )
