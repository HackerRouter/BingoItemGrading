"""种植：种子 → 作物方块 → 产物。

为什么需要这一层：作物方块（`blocks/torchflower`、`blocks/wheat` 这些）的
战利品表在来源索引里是 `block_drop`，但**它们不自然生成**——`block_density`
里没有它们，结构放置也没有，于是 `_block()` 的四条模型（结构 / 地表露头 /
洞穴暴露 / 3D 挖掘）全部返回 None。真实来源是「种下去、等它长熟、收割」。

模型口径（用户定的简化）：

- **不算耕地**：拿到种子直接种，不建模锄地、水渠、光照；
- **长出时长按随机刻机制算**：阶段数来自作物自己（`CROP_MAX_AGE`），每阶段
  期望 204.8 秒（子区块每 tick 3 次抽取 × 1/3 推进概率，见 `gamedata`）。
  这是**最佳条件（单株、湿润耕地）**的下界：相邻同种作物会把速度减半。
- **骨粉单独一条动作**：用量来自 wiki「每次骨粉推进几个阶段」，与自然生长
  无关，两条路让引擎自己挑便宜的。

一株收多少不看方块掉落表的原始 rolls，而是用 `loot_per_chest_all` 给出的
**每次触发的期望**（`torchflower` 1.0、`pitcher_crop` 的分阶段 entry 已经折进
期望里），所以凑够 1 个需要的株数就是 `1 / per_item`。
"""

from __future__ import annotations

from bingo_grading import gamedata
from bingo_grading.case.context import CaseContext
from bingo_grading.plan import Action, Requirement
from bingo_grading.plan.actions import MODE_PER_USE
from bingo_grading.sources import index as source_index

from .common import _short
from .graph import GraphActions


BONE_MEAL = "minecraft:bone_meal"


def plant_crop(
    record: source_index.SourceRecord,
    ctx: CaseContext,
    result: GraphActions,
) -> int:
    """给一个作物方块记录造「种植」动作，返回造出几条（0 表示不是作物）。"""
    crop = record.subject
    seed = gamedata.CROP_SEEDS.get(crop)
    if seed is None:
        return 0
    got = ctx.loot_per_chest_all(crop)
    per_item = 0.0
    if got is not None:
        per_item = float(got[0].get(record.item, 0.0))
    if per_item <= 0:
        # 有些作物表的期望算不出来：`minecraft:blocks/pitcher_plant` 用的是
        # `match_block` 条件（判断方块是不是成熟植株），`loot/expect.py` 还不认
        # 这个条件类型，于是 `per_trigger_expected` 是空表。
        # 退化口径：**成熟作物收 1 个自己**——这不是拍的数，是这张表的实际语义。
        # 记账留着，免得「期望缺失」被当成「有数据」。
        result.uncovered[f"期望缺失按每株 1 个:{crop}"] += 1
        per_item = 1.0

    # 胡萝卜、马铃薯这类**拿自己当种子**：一株投入 1 个、收 per_item 个，
    # 真正多出来的是 `per_item - 1`。写成 `yields` 与 `requires` 同时含该物品
    # 会被 `Action` 判成自相矛盾，所以这里用**净增**口径：投入已在产量里抵掉。
    surplus = per_item
    seed_requires: tuple[Requirement, ...] = (
        Requirement(seed, 1.0, MODE_PER_USE),
    )
    if seed == record.item:
        surplus = per_item - 1.0
        seed_requires = ()
        if surplus <= 0:
            result.uncovered[f"该作物自种不增产:{crop}"] += 1
            return 0

    made = 0
    base_id = f"plant:{_short(record.item)}:{_short(crop)}"
    # 一株的周期 = 长熟 + 收割；凑 1 个要 `1/surplus` 株。
    grow_seconds = gamedata.crop_grow_seconds(crop)
    if grow_seconds is None:
        result.uncovered[f"作物阶段数未知:{crop}"] += 1
        return 0
    natural = (grow_seconds + gamedata.CROP_HARVEST_SECONDS) / surplus
    result.emit(
        Action(
            action_id=base_id,
            item=record.item,
            cost=natural,
            yields={record.item: 1.0},
            requires=seed_requires,
            label=(
                f"种 {_short(crop)}：{_short(seed)} 种下、长熟、收割"
                f"（每株净得 {surplus:.2f} 个，凑 1 个要 {1.0 / surplus:.1f} 株）"
            ),
            source=f"crop:{crop}",
        )
    )
    made += 1

    uses = gamedata.BONEMEAL_USES.get(crop)
    if uses:
        # 骨粉路径不吃自然生长时长：催熟后立刻成熟，只剩使用与收割时间。
        fast = (
            uses * gamedata.BONEMEAL_SECONDS_PER_USE + gamedata.CROP_HARVEST_SECONDS
        ) / surplus
        result.emit(
            Action(
                action_id=f"{base_id}:bonemeal",
                item=record.item,
                cost=fast,
                yields={record.item: 1.0},
                requires=seed_requires
                + (Requirement(BONE_MEAL, float(uses), MODE_PER_USE),),
                label=f"种 {_short(crop)} 并用 {uses} 份骨粉催熟",
                source=f"crop_bonemeal:{crop}",
            )
        )
        made += 1
    return made
