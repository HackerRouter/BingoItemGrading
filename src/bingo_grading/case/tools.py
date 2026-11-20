"""工具链：把「工具」当成目标物品，按配方 IR 展开成动作。

挖矿的工具要求来自 RA 的 `harvest.jsonl`（方块 → 最弱合格工具）。工具本身不是
常量，而是一件普通物品：

```text
铁镐 ← 3 铁锭 + 2 木棍
木棍 ← 2 木板            （配方原料是 `#planks`，已按 tag 展开）
木板 ← 1 原木
铁锭 ← 熔炼铁矿石          （时间与燃料由 `ctx.smelt` 计）
```

这里递归展开这条链，让引擎按普通物品给工具定价：挖矿动作挂一个 `once` 前置，
方案里只收一次工具成本。采集物（原木、矿石）由 `ctx.mining` 的密度数据生成动作。
"""

from __future__ import annotations

import itertools
import math

from bingo_grading.case.context import CaseContext
from bingo_grading.case.sources import (
    ActionBundle,
    craft,
    mine_cave,
    mine_surface,
    mine_vein,
    smelt,
)
from bingo_grading.recipes import facts

MAX_DEPTH = 8

# 单条配方最多展开多少个原料组合。笛卡尔积本身不大（实测最大 169），
# 但每种组合都要递归展开原料、各自建一个动作，全展开会把动作集灌满。
# 这是搜索预算，不是事实数据：保留最便宜的若干个足以重现最优与次优。
MAX_COMBOS = 32


def produced_items(bundle: ActionBundle) -> set[str]:
    """动作集当前能产出的全部物品。"""
    return {name for action in bundle.actions for name in action.yields}


def block_is_open(ctx: CaseContext, block: str) -> bool:
    """该方块能走过去/游过去拿到吗？

    优先看上游 `cave-exposure` 的 6 面实测（贴天空/水的比例），
    没有那份数据时退回段填充率（主段上方段的干实心占比）。

    两边都不靠方块名：后缀白名单把 `bamboo`（天空暴露 96%）当成矿道方块，
    算出 64 TU，而正确模型只有 1.04 TU。
    """
    exposure = ctx.block_exposure(block)
    if exposure is not None:
        return exposure[0].walkable > 0
    found = ctx.block_openness(block)
    if found is None:
        return False  # 没有数据：不能默认当敞开
    return found[0] < ctx.OPEN_SECTION_FILL


def estimate_cost(
    ctx: CaseContext,
    item: str,
    *,
    depth: int = MAX_DEPTH,
    cache: dict[str, float] | None = None,
    stack: set[str] | None = None,
    state: dict[str, bool] | None = None,
) -> float:
    """快速估算某物品的获取成本，只用于比较同一槽位的候选。

    采集物按采集单价；合成物按**全部**配方递归取最小（同一产出常有多条配方：
    铁锭可以熔炼矿石、爆烤矿石、拆铁块、拆金粒，价差很大）。
    与引擎的完整曲线不同，这里忽略固定成本与竞争，用于**排序**足够：
    `oak_wood`（4 原木 → 3 木）必然比直接 `oak_log` 贵，会被排到后面。

    环用**当前路径**标记（`stack`），且被环或深度截断过的结果**不写缓存**：
    铁粒能从烧铁镐得到，算铁锭时会绕到铁镐再回到铁锭；若把这次绕路
    得到的 `inf` 留在缓存里，之后单独算铁镐就永远无解。
    """
    cache = {} if cache is None else cache
    stack = set() if stack is None else stack
    state = {"cut": False} if state is None else state
    if item in cache:
        return cache[item]
    if item in stack:
        state["cut"] = True
        return math.inf  # 环：这条路径不可用
    stack.add(item)
    outer = state["cut"]
    state["cut"] = False
    best = math.inf
    try:
        found = ctx.surface_block_parts(item)
        if found is not None:
            best = min(best, found[0].value + found[1].value)
        cave = ctx.cave_block_parts(item)
        if cave is not None:
            best = min(best, cave[0].value + cave[1].value)
        estimate, sourced = ctx.mining(item, target_items=1.0)
        if (
            estimate is not None
            and estimate.best is not None
            and sourced is not None
        ):
            best = min(best, sourced.value)
        if depth > 0:
            conversions, _layer = ctx.recipe_conversions(item)
            for conversion in conversions:
                priced = _conversion_cost(
                    ctx, conversion, depth=depth, cache=cache, stack=stack, state=state
                )
                if priced is not None:
                    best = min(best, priced[0])
        elif not math.isinf(best):
            state["cut"] = True  # 深度用尽：合成侧没算完
    finally:
        local = state["cut"]
        state["cut"] = outer or local
        stack.discard(item)
    if not local:
        cache[item] = best
    return best


def _conversion_cost(
    ctx: CaseContext,
    conversion: facts.Conversion,
    *,
    depth: int,
    cache: dict[str, float],
    stack: set[str],
    state: dict[str, bool],
) -> tuple[float, dict[str, float]] | None:
    """一条折算的单位成本，以及各槽挑中的原料。不可行返回 `None`。

    每个槽位独立按代价挑候选——这就是「木棍从树叶能来、但主流量产走木板」
    这类问题的处理方式：不看结构，只看合成链总价。
    """
    ingredients: dict[str, float] = {}
    total = 0.0
    for choices, qty in zip(conversion.candidates, conversion.slot_qty):
        cost, name = min(
            (
                estimate_cost(
                    ctx, choice, depth=depth - 1, cache=cache, stack=stack, state=state
                ),
                choice,
            )
            for choice in choices
        )
        if math.isinf(cost):
            return None
        ingredients[name] = ingredients.get(name, 0.0) + qty
        total += cost * qty
    return total / max(conversion.yields, 1e-9), ingredients


def _describe(conversion: facts.Conversion, ingredients: dict[str, float]) -> str:
    """按**实际挑中**的原料写说明（`Conversion.detail` 用的是候选代表，会骗人）。"""
    ins = "、".join(f"{qty:g}×{name}" for name, qty in sorted(ingredients.items()))
    return (
        f"{ins} → {conversion.yields:g}×{conversion.output}"
        f"（{conversion.serializer or 'recipe'}；{conversion.source_file}）"
    )


def _melted(conversion: facts.Conversion) -> bool:
    """熔炼 / 爆烤这类「单原料 + 燃料」的配方。"""
    return conversion.serializer.startswith(
        ("minecraft:smelting", "minecraft:blasting")
    )


def _ingredient_combos(
    ctx: CaseContext,
    conversion: facts.Conversion,
    *,
    depth: int,
    cache: dict[str, float],
    stack: set[str],
    state: dict[str, bool],
) -> tuple[list[tuple[float, dict[str, float]]], int]:
    """一条配方全部可行的原料组合（按单位成本升序），以及截断前的组合总数。

    每个槽位先用 `estimate_cost` 筛掉无来源的候选（`inf`），再取笛卡尔积。
    `estimate_cost` 在这里只做**可行性筛选与排序**，不替调用方拍板：
    落选的组合也要建动作，否则次优路径在求解层根本不存在，无从展示。
    第二个返回值给调用方判断是否撞上 `MAX_COMBOS`——截断不能默默发生。
    """
    slots: list[list[tuple[float, str]]] = []
    for choices, _qty in zip(conversion.candidates, conversion.slot_qty):
        options = []
        for choice in choices:
            cost = estimate_cost(
                ctx, choice, depth=depth - 1, cache=cache, stack=stack, state=state
            )
            if math.isinf(cost):
                continue
            options.append((cost, choice))
        if not options:
            return [], 0
        options.sort()
        slots.append(options)
    combos: list[tuple[float, dict[str, float]]] = []
    for picked in itertools.product(*slots):
        total = 0.0
        ingredients: dict[str, float] = {}
        for (cost, name), qty in zip(picked, conversion.slot_qty):
            total += cost * qty
            ingredients[name] = ingredients.get(name, 0.0) + qty
        combos.append((total / max(conversion.yields, 1e-9), ingredients))
    combos.sort(key=lambda combo: (combo[0], tuple(sorted(combo[1].items()))))
    return combos[:MAX_COMBOS], len(combos)


def ensure_tool(
    bundle: ActionBundle,
    ctx: CaseContext,
    item: str,
    *,
    depth: int = MAX_DEPTH,
    _memo: dict | None = None,
) -> bool:
    """确保动作集里有产出 `item` 的动作。返回是否成功。

    已能产出时直接返回（不重复造）；否则把**全部配方 × 全部可行槽位候选**
    展开成动作，叶节点（没有配方的物品）用密度数据生成采集动作。

    最便宜的那条用 `tool:craft:<item>` 这个不带后缀的 ID，其余按代价升序
    用 `tool:craft:<item>~2`、`~3`……——于是 `Plan.alternatives` 里能同时
    看到最优与次优合计路径，它们的单价由求解器自己算，不是这里写死。

    `expanding` 是**当前展开路径**：同一条链上要求物品自给（铁粒 ← 烧铁镐
    ← 铁锭 ← 铁粒）直接判不可行，否则「拆粒」这类环配方会展开出一堆
    烧工具换铁粒的荒谬动作。`_memo` 让整棵树共享估算缓存与已展开集合。
    """
    memo = (
        {
            "done": set(),
            "expanding": set(),
            "cache": {},
            "stack": set(),
            "state": {"cut": False},
        }
        if _memo is None
        else _memo
    )
    if item in memo["done"]:
        return True
    if item in memo["expanding"]:
        return False  # 环：这条路径上不能自己给自己当原料
    if item in produced_items(bundle):
        memo["done"].add(item)
        return True
    if depth <= 0:
        bundle.note(f"工具链递归过深，{item} 没有来源")
        return False
    conversions, _layer = ctx.recipe_conversions(item)
    if not conversions:
        if _collect(bundle, ctx, item):
            memo["done"].add(item)
            return True
        return False
    memo["expanding"].add(item)
    made = 0
    try:
        plans: list[tuple[float, facts.Conversion, dict[str, float]]] = []
        seen: set[tuple[str, tuple[tuple[str, float], ...]]] = set()
        for conversion in conversions:
            combos, total = _ingredient_combos(
                ctx,
                conversion,
                depth=depth,
                cache=memo["cache"],
                stack=memo["stack"],
                state=memo["state"],
            )
            if total > len(combos):
                # 截断要说出来：否则「次优路径没展示」会被误读成「不存在」
                bundle.note(
                    f"{item} 的配方 {conversion.source_file} 有 {total} 种原料组合，"
                    f"只展开最便宜的 {len(combos)} 种（MAX_COMBOS={MAX_COMBOS}）"
                )
            for cost, ingredients in combos:
                # 同一组原料只建一个动作：熔炼与爆烤、有序与无序合成在当前
                # 成本模型里算的是同一笔账，重复建只会给求解器添冗余。
                signature = (
                    "smelt" if _melted(conversion) else "craft",
                    tuple(sorted(ingredients.items())),
                )
                if signature in seen:
                    continue
                seen.add(signature)
                plans.append((cost, conversion, ingredients))
        plans.sort(
            key=lambda plan: (
                plan[0],
                plan[1].source_file,
                tuple(sorted(plan[2].items())),
            )
        )
        for index, (_cost, conversion, ingredients) in enumerate(plans, start=1):
            if not all(
                ensure_tool(bundle, ctx, ingredient, depth=depth - 1, _memo=memo)
                for ingredient in ingredients
            ):
                continue  # 这条组合缺原料（或踩到环），跳过；其他组合仍可成立
            suffix = "" if index == 1 else f"~{index}"
            if _melted(conversion):
                raw = sorted(ingredients)[0]
                bundle.add(
                    smelt(
                        bundle,
                        ctx,
                        item=item,
                        raw=raw,
                        batch=conversion.yields,
                        action_id=f"tool:smelt:{item}{suffix}",
                    )
                )
            else:
                bundle.add(
                    craft(
                        bundle,
                        action_id=f"tool:craft:{item}{suffix}",
                        yields={item: conversion.yields},
                        inputs=ingredients,
                        label=f"造 {item}（{_describe(conversion, ingredients)}）",
                    )
                )
            made += 1
    finally:
        memo["expanding"].discard(item)
    if made:
        memo["done"].add(item)
        return True
    bundle.note(f"工具链缺原料（{item}），该工具缺席")
    return False


def _collect(bundle: ActionBundle, ctx: CaseContext, item: str) -> bool:
    """没有配方的物品：把**两条来源都摆上**，让求解器按需选。

    同一个方块常常两种取法都成立：粘土在地表（河床）每区块只有 2.6 块但走过去就能捡，
    在地下（深部沉积）量大却要挖矿道。二选一会把便宜的那半边丢掉；两条都进曲线，
    引擎会先用完地表那点白菜价，再转到挖掘。

    `tool:surface:<物品>` 带一次性「找首片」固定成本，`tool:vein:<物品>` 带竖井固定成本，
    两者都由引擎按需求量取舍。
    """
    made = 0
    surface = mine_surface(
        bundle,
        ctx,
        block=item,
        item=item,
        batch=1.0,
        action_id=f"tool:surface:{item}",
    )
    if surface is not None:
        bundle.add(surface)
        made += 1
    cave = mine_cave(
        bundle,
        ctx,
        block=item,
        item=item,
        batch=1.0,
        action_id=f"tool:cave:{item}",
    )
    if cave is not None:
        bundle.add(cave)
        made += 1
    vein = mine_vein(
        bundle,
        ctx,
        block=item,
        item=item,
        batch=1.0,
        action_id=f"tool:vein:{item}",
    )
    if vein is not None:
        bundle.add(vein)
        made += 1
    if not made:
        bundle.note(f"工具链需要 {item}，但没有可用的采集数据")
        return False
    return True
