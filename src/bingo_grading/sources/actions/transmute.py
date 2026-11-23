"""方块变换：`transmutes` 边 → 来源（刮蜡、去皮、混凝土凝固）。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from bingo_grading import paths
from bingo_grading import units
from bingo_grading import gamedata
from bingo_grading import copper_facts
from bingo_grading import mining_facts
from bingo_grading.case.context import CaseContext
from bingo_grading.case.sources import seconds
from bingo_grading.plan import Action, Requirement
from bingo_grading.plan.actions import MODE_ONCE, MODE_PER_USE
from bingo_grading.sources import constructs as _constructs
from bingo_grading.sources import graph as _graph

from .common import _short
from .graph import GraphActions




def _placeholder_variants(
    prefix: str, ctx: CaseContext, result: GraphActions
) -> list[tuple[str, tuple[Requirement, ...]]]:
    """`capability:lava_access@*` → 每段岩浆湖一个 `capability:lava_access@<段>`。"""
    if not prefix.startswith("capability:lava_access"):
        return []
    out: list[tuple[str, tuple[Requirement, ...]]] = []
    for source in ctx.patch_sources(_constructs.LAVA):
        access = f"{prefix}@{source.key}"
        result.emit(
            Action(
                action_id=f"travel:{source.key}",
                item=access,
                cost=source.cost_tu,
                yields={access: 1.0},
                label=source.where or f"到达 {source.subject} 的一片",
                source="block_density" if source.kind == "shaft" else "structure_density",
            )
        )
        # 铁桶可重复用，但它自己也有一条物品来源链；由调用方决定挂不挂
        # （构造表里已经把它列进 inputs 了，别再挂一次）。
        batch = _constructs.CAST_BATCH
        result.emit(
            Action(
                action_id=f"bucket:lava@{source.key}",
                item=_constructs.LAVA,
                cost=seconds(gamedata.BUCKET_FILL_SECONDS * batch),
                yields={_constructs.LAVA: batch},
                capacity=source.capacity_batches(batch),
                requires=(Requirement(access, 1.0, MODE_ONCE),),
                label=f"在岩浆边装 {batch:g} 桶（{source.where}）",
                source="calibration",
            )
        )
        out.append((access, ()))
    return out



def _transform_sources(
    item: str,
    ctx: CaseContext,
    result: GraphActions,
    once_caps: set[str],
    depth: int = 0,
) -> None:
    """以该物品为产出的世界交互规则（来自 `graph.json` 的 `transmutes` 边）。

    浇铸黑曜石这类「方块更新」不走战利品表也不走配方，但产出与成本都有据
    （`CAST_SECONDS_PER_BLOCK`），所以照常入图。
    """
    _transmute_sources(item, ctx, result)
    if item != _constructs.OBSIDIAN:
        return
    for variant, extra in _placeholder_variants(
        _constructs.LAVA_ACCESS, ctx, result
    ):
        result.emit(
            Action(
                action_id=f"cast:obsidian@{_short(variant)}",
                item=_constructs.OBSIDIAN,
                cost=seconds(
                    gamedata.CAST_SECONDS_PER_BLOCK * _constructs.CAST_BATCH
                    + _constructs.CAST_BATCH * gamedata.BUCKET_FILL_SECONDS
                ),
                yields={_constructs.OBSIDIAN: _constructs.CAST_BATCH},
                requires=(Requirement(variant, 1.0, MODE_ONCE), *extra),
                label=(
                    f"倒 {_constructs.CAST_BATCH:g} 桶岩浆浇成黑曜石"
                    f"（浇出来直接就是门框，不用挖）"
                ),
                source="game_rule:cast:obsidian",
            )
        )



# ---------------------------------------------------------------- 方块变换
#
# RA 的 `graph.json` 把「方块 A + 条件 → 方块 B」显式导出成 `transmutes` 边，
# 两类来源：
#
# - `code/transform`（237 条）：`block_transformer/*.json` 的斧头/锹/蜜脾交互
#   ——刮蜡、去氧化、去皮、压小径；
# - `bridge/convention`（36 条）：数据包里没有、由代码决定的约定变换。
#   目前只有一条规则 `water_solidify`：`*_concrete_powder` 遇水固化成
#   `*_concrete`（16 色）。
#
# 这两类都是**真实获取路线**，既不是配方也不是战利品表。以前一条都没接，
# 于是 15 色混凝土直接不可得、`oxidized_copper_door` 只能跑去矿井碰运气。

WATER_SOURCE = "capability:water_source"

WATER_SOURCE_ACTION = "water:source"


# `tool:<类别>` 是**工具类别**，不是物品名。取该类别里最弱的那把：
# 变换不需要更好的工具，而木制工具是玩家最早能造出来的（3 木板 + 2 木棍）。
WEAKEST_TOOL = {
    "minecraft:axe": "minecraft:wooden_axe",
    "minecraft:pickaxe": "minecraft:wooden_pickaxe",
    "minecraft:shovel": "minecraft:wooden_shovel",
    "minecraft:hoe": "minecraft:wooden_hoe",
    "minecraft:sword": "minecraft:wooden_sword",
    "minecraft:shears": "minecraft:shears",
    "minecraft:flint_and_steel": "minecraft:flint_and_steel",
}



@lru_cache(maxsize=4)
def _transmute_rules(path: str) -> dict[str, tuple[tuple[str, tuple[str, ...], str, bool], ...]]:
    """`graph.json` 的 `transmutes` 边 → `{产物物品: ((规则 id, body, 族, 是否逆向), …)}`。

    `head` 在产物里是 `block:<方块>`，下游要的是同名物品，所以剥掉前缀当键。
    """
    try:
        loaded = _graph.load(Path(path))
    except _graph.GraphError:
        return {}
    out: dict[str, list[tuple[str, tuple[str, ...], str, bool]]] = {}
    for rule in loaded.rules:
        if rule.kind != "transmutes" or not rule.head.startswith("block:"):
            continue
        product = rule.head[len("block:"):]
        meta = rule.meta or {}
        family = str(meta.get("convention") or rule.family)
        out.setdefault(product, []).append(
            (rule.id, rule.body, family, bool(meta.get("inverse")))
        )
    return {name: tuple(rules) for name, rules in out.items()}



def _ensure_water_source(ctx: CaseContext, result: GraphActions, once_caps: set[str]) -> str | None:
    """「有水的地方」这条能力：走到最近水域装一桶水。

    水桶可反复倒，所以是 `once`。成本复用 `water_search_cost()`
    （`biome_patch` 的面积占比法，与抓鱼同一条路）。
    """
    if WATER_SOURCE in once_caps:
        return WATER_SOURCE
    found = ctx.water_search_cost()
    if found is None:
        return None
    cost, detail = found
    result.emit(
        Action(
            action_id=WATER_SOURCE_ACTION,
            item=WATER_SOURCE,
            cost=cost.value,
            yields={WATER_SOURCE: 1.0},
            label=f"走到水边装水（{detail.split('；')[0]}）",
            source=cost.source,
        )
    )
    once_caps.add(WATER_SOURCE)
    return WATER_SOURCE



def _transmute_sources(item: str, ctx: CaseContext, result: GraphActions) -> None:
    """RA 图里以该物品为产出的 `transmutes` 边 → 动作。

    成本按变换方式分两类：

    - `water_solidify`：把粉末方块放下去、倒水、再挖掉——付**一次破坏**；
    - 其余（斧头/锹/蜜脾）：只为一次右键（`WAX_OFF_SECONDS`）。

    依赖前缀：`block:` / `item:` 是消耗品（`per_use`），`tool:` 是工具
    （`once`，可反复用），`assume:water_source` 是环境能力（也 `once`）。

    **铜氧化的 `assume:time` 规则跳过**：`code/transform` 里同一批方块还有一条
    「放着等它痂」的规则，那是同一件事的另一种说法，而真实路线已由
    `_oxidation_source()` 按 `copper_facts` 接上（1600/1200/1200 秒）。
    不跳过的话 45 条规则每条都会记一次「未建模的变换依赖」，把 `uncovered`
    榜首顶成 78 次纯噪声。**只跳这一种节点**：铜族的去皮/刮蜡同样是真实路线。
    """
    resolved = paths.recipe_analysis(ctx.pack_version())
    if not resolved.exists:
        return
    oxidizable = copper_facts.load(ctx.pack_version())
    rules = _transmute_rules(str(resolved.path / "graph.json")).get(item)
    if not rules:
        return
    for rule_id, body, family, inverse in rules:
        requires: list[Requirement] = []
        source_item: str | None = None
        usable = True
        for node in body:
            if node.startswith("block:"):
                name = node[len("block:"):]
                source_item = name
                requires.append(Requirement(name, 1.0, MODE_PER_USE))
            elif node.startswith("item:"):
                requires.append(Requirement(node[len("item:"):], 1.0, MODE_PER_USE))
            elif node.startswith("tool:"):
                category = node[len("tool:"):]
                tool = WEAKEST_TOOL.get(category)
                if tool is None:
                    # 不认识的工具类别不猜：路照走，工具成本没算，记一笔。
                    result.uncovered[f"未建模的工具类别:{category}"] += 1
                    continue
                requires.append(Requirement(tool, 1.0, MODE_ONCE))
                result.transmute_needs.add(tool)
            elif node == "assume:water_source":
                capability = _ensure_water_source(ctx, result, result.once_caps)
                if capability is None:
                    usable = False
                    break
                requires.append(Requirement(capability, 1.0, MODE_ONCE))
            else:
                # 铜氧化：真实路线已由 `_oxidation_source` 给出，这条
                # `assume:time` 规则是同一件事的另一种写法。跳过**这条规则**，
                # 不记账（否则 `uncovered` 里会多出一批纯噪声）。
                if node == "assume:time" and item in oxidizable:
                    usable = False
                    break
                # 不认识的依赖不猜：宁可这条路缺席，也不要凭空免费。
                result.uncovered[f"未建模的变换依赖:{node}"] += 1
                usable = False
                break
        if not usable or source_item is None:
            continue
        if family == "water_solidify":
            cost = seconds(
                mining_facts.break_seconds(item, fallback="stone") + gamedata.PLACE_SECONDS
            )
            label = f"放下 {_short(source_item)}、倒水固化成 {_short(item)}，再挖掉"
        else:
            cost = seconds(gamedata.WAX_OFF_SECONDS)
            verb = "涂回蜡" if inverse else "变换"
            label = f"用 {_short(rule_id.split(':')[0])} 把 {_short(source_item)} {verb}成 {_short(item)}"
        result.emit(
            Action(
                action_id=f"transmute:{_short(item)}:{_short(source_item)}",
                item=item,
                cost=cost,
                yields={item: 1.0},
                requires=tuple(requires),
                label=label,
                source=f"graph:transmutes:{family}",
            )
        )
        # 原料要自己有来源；推迟到主链之后 visit（见 `GraphActions.transmute_needs`）。
        result.transmute_needs.add(source_item)
        result.transmute_needs.update(
            node.split(":", 1)[1]
            for node in body
            if node.startswith(("item:", "tool:"))
        )
