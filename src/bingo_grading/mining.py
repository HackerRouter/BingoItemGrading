"""挖掘代价：从「每区块有多少」换算到 TU。

## 两种挖法，代价公式不同

| 挖法 | 拿到目标方块要挖掉的方块数 | 说明 |
|---|---|---|
| 鱼骨矿道 | `目标数 / 体积密度` | 挖掉路径上的一切，路径上的矿全部入包 |
| 挖竖井到某层 | `深度 × 截面` | 只为到达，不指望沿途有矿 |

两者都是「挖掉的方块数 × 每方块秒数 ÷ 每 TU 秒数」。

## 体积密度的分母

`ore_density.per_chunk_density` 的分母是**该群系等效区块数**，即一个 16×16 全高的柱。
换算到体积密度要除以柱的体积：

```
ρ_vol = per_chunk_density / (16 × 16 × 段高)
```

段高取该纵段的高度（上游每 16 格一段），不是整柱 384。用整柱会把
「这段特别富」稀释掉——恶地金矿在地表附近，整柱平均会低估它的富集。

## 期望与聚簇无关

挖矿道拿到 k 块的代价是 `k / ρ_vol` 个方块，与矿石是否成簇无关
（簇的碰撞截面更大但簇数更少，期望抵消）。见 ADR 0015。

## 到达该层：当前是上界

「挖竖井下去」假设沿途没有洞穴可用。若将来补上地下空洞率（C11），
可以把这段换成「走洞穴 + 短距离接驳」，代价会明显下降。当前结果因此是上界，
`assumptions` 会写明。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import mining_facts
from .gamedata import (
    BIOME_SPECIFIC_ORES,
    DEEPSLATE_BELOW_Y,
    DEFAULT_BLOCK,
    DEFAULT_SWATH,
    MIN_DENSITY_BLOCKS,
    SURFACE_Y,
    SURFACE_Y_BY_DIMENSION,
    UNDERGROUND_MINING_MATERIAL,
)
from .units import SECONDS_PER_TU

# 区块水平面积（方块²）。
CHUNK_FOOTPRINT = 16 * 16

# 群系矿集合、各维度地表高度、默认围岩与深板岩界线都是**游戏数据**，
# 定义在 `gamedata.py`（那里有取值依据）；本模块只需引用名字。


def surrounding_block(y: int, dimension: str = "minecraft:overworld") -> str:
    """该高度处的围岩类型。挖矿道挖掉的大多是它，不是目标矿。

    下界没有深板岩：整块都是下界岩，比石头软得多（0.10 vs 0.40 秒/块），
    这个差异是下界挖矿路线的核心优势，不能按主世界算。
    """
    if dimension == "minecraft:the_nether":
        return "netherrack"
    return "deepslate" if y < DEEPSLATE_BELOW_Y else DEFAULT_BLOCK


def surface_y_for(dimension: str = "minecraft:overworld") -> int:
    """该维度的地表高度。未知维度按主世界。"""
    return SURFACE_Y_BY_DIMENSION.get(dimension, SURFACE_Y)


class MiningError(ValueError):
    """挖矿代价参数不合法。"""


@dataclass(frozen=True)
class SectionCost:
    """在一个纵段里挖矿的代价。"""

    y_range: tuple[int, int]
    per_chunk_density: float
    volume_density: float
    blocks_to_break: float
    tunnel_tu: float
    shaft_tu: float
    break_block: str

    @property
    def total_tu(self) -> float:
        return self.tunnel_tu + self.shaft_tu

    def as_dict(self) -> dict:
        return {
            "y_range": list(self.y_range),
            "per_chunk_density": round(self.per_chunk_density, 4),
            "volume_density": round(self.volume_density, 8),
            "blocks_to_break": round(self.blocks_to_break, 2),
            "tunnel_tu": round(self.tunnel_tu, 3),
            "shaft_tu": round(self.shaft_tu, 3),
            "total_tu": round(self.total_tu, 3),
            "break_block": self.break_block,
        }


@dataclass
class MiningEstimate:
    """一个（群系, 方块）组合的挖掘代价。"""

    biome: str
    subject: str
    target_items: float
    sections: list[SectionCost] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    # 上游的区块级 `reliable`。只做记录，不决定代价可不可用。
    chunk_reliable: bool | None = None
    # 数到的方块数。密度估计的误差由它主导，是可信度的真正依据。
    sample_blocks: int | None = None

    @property
    def density_trusted(self) -> bool | None:
        """密度是否够用。判据是方块数，不是区块数；未知时返回 None。"""
        if self.sample_blocks is None:
            return None
        return self.sample_blocks >= MIN_DENSITY_BLOCKS

    @property
    def best(self) -> SectionCost | None:
        """代价最小的纵段——玩家会挑最划算的层挖。"""
        if not self.sections:
            return None
        return min(self.sections, key=lambda item: item.total_tu)

    @property
    def cost_tu(self) -> float | None:
        """最便宜那一段的代价。

       **不设下限**：极富的段算出来可以远小于 1 TU（比如每区块 10 万块），
        那是真实值——乘上需求数量后就不可忽略了，静默抬到 1 TU 会让
        「矿富的地方几乎免费」这类结论失真。
        """
        best = self.best
        return None if best is None else best.total_tu

    def as_dict(self) -> dict:
        best = self.best
        return {
            "biome": self.biome,
            "subject": self.subject,
            "target_items": self.target_items,
            "density_trusted": self.density_trusted,
            "sample_blocks": self.sample_blocks,
            "chunk_reliable": self.chunk_reliable,
            "cost_tu": None if best is None else round(best.total_tu, 3),
            "best_section": None if best is None else best.as_dict(),
            "all_sections": [section.as_dict() for section in self.sections],
            "assumptions": sorted(set(self.assumptions)),
        }


def volume_density(per_chunk_density: float, section_height: int) -> float:
    """每区块方块数 → 每方块³的密度。"""
    if section_height <= 0:
        raise MiningError(f"段高必须为正：{section_height}")
    if per_chunk_density < 0:
        raise MiningError(f"密度不能为负：{per_chunk_density}")
    return per_chunk_density / (CHUNK_FOOTPRINT * section_height)


def blocks_per_item(density: float) -> float:
    """撞到 1 块目标方块平均要挖掉多少方块。密度为 0 时返回 inf。"""
    if density <= 0:
        return math.inf
    return 1.0 / density


def tunnel_cost(
    density: float,
    *,
    target_items: float = 1.0,
    break_seconds: float | None = None,
) -> float:
    """挖矿道拿到 `target_items` 块方块的代价（TU）。

    挖矿道扫过的一切方块都会被挖掉，所以代价只看「挖掉多少方块」，
    与目标方块在不在同一条路径上无关（直线路径必然穿过密度场）。

    `break_seconds` 不给时按**地下开矿口径**（铁质工具）算 `DEFAULT_BLOCK`。
    """
    if target_items <= 0:
        return 0.0
    if break_seconds is None:
        break_seconds = mining_facts.break_seconds(
            DEFAULT_BLOCK, material=UNDERGROUND_MINING_MATERIAL
        )
    per_item = blocks_per_item(density)
    if math.isinf(per_item):
        return math.inf
    blocks = per_item * target_items
    return blocks * break_seconds / SECONDS_PER_TU


def shaft_cost(
    from_y: int,
    to_y: int,
    *,
    break_seconds: float | None = None,
    swath: float = DEFAULT_SWATH,
) -> float:
    """垂直挖竖井从 `from_y` 到 `to_y` 的代价（TU）。

    只算挖掉的方块；下落本身不耗时（挖穿后掉下去），所以不额外加移动时间。
    截面 `swath` 与矿道同一口径（1 宽 × 2 高），否则同一个「下挖 70 格」
    在挖矿与岩浆两条路线上会差一倍。

    `break_seconds` 不给时按**地下开矿口径**（铁质工具）算。
    """
    depth = abs(from_y - to_y)
    if break_seconds is None:
        break_seconds = mining_facts.break_seconds(
            DEFAULT_BLOCK, material=UNDERGROUND_MINING_MATERIAL
        )
    return depth * swath * break_seconds / SECONDS_PER_TU


def estimate(
    *,
    biome: str,
    subject: str,
    sections: dict[str, dict],
    target_items: float = 1.0,
    surface_y: int | None = None,
    dimension: str = "minecraft:overworld",
    break_block: str | None = None,
    entries_per_block: float = 1.0,
) -> MiningEstimate:
    """按纵段求最优挖掘代价。

    `sections` 是 `ore_density.value.by_section`：`{起始Y: {y_range, per_chunk, ...}}`。

    `entries_per_block` 是「一块方块掉几个目标物品」（红石矿单块掉 4–5 个红石粉）。
    它把「要挖几块方块」换算成「要挖几块目标方块」。

    `break_block` 留空时按维度与层位自动选：下界用下界岩，y < 0 用深板岩，其余用石头。
    `surface_y` 留空时按维度取默认地表高度。
    """
    if entries_per_block <= 0:
        raise MiningError(f"每方块产出必须为正：{entries_per_block}")
    if break_block is not None and not mining_facts.load().known(break_block):
        raise MiningError(f"未知方块类型 {break_block!r}")
    if surface_y is None:
        surface_y = surface_y_for(dimension)

    result = MiningEstimate(biome=biome, subject=subject, target_items=target_items)
    if not sections:
        result.assumptions.append("没有纵段数据，无法估算")
        return result

    # 掉落数量：拿 1 个物品只需 1/entries_per_block 块方块。
    blocks_needed = target_items / entries_per_block
    auto_block = break_block is None
    used_blocks: set[str] = set()

    for _, cell in sorted(sections.items(), key=lambda kv: int(kv[0])):
        y_range = cell.get("y_range") or []
        per_chunk = cell.get("per_chunk")
        if len(y_range) != 2 or per_chunk is None:
            continue
        low, high = int(y_range[0]), int(y_range[1])
        height = high - low + 1
        density = volume_density(float(per_chunk), height)
        center = (low + high) // 2

        block = break_block if break_block is not None else surrounding_block(center, dimension)
        used_blocks.add(block)
        break_seconds = mining_facts.break_seconds(block, material=UNDERGROUND_MINING_MATERIAL)

        tunnel = tunnel_cost(density, target_items=blocks_needed, break_seconds=break_seconds)
        shaft = shaft_cost(surface_y, center, break_seconds=break_seconds)

        result.sections.append(
            SectionCost(
                y_range=(low, high),
                per_chunk_density=float(per_chunk),
                volume_density=density,
                blocks_to_break=math.inf if math.isinf(tunnel) else blocks_needed / density,
                tunnel_tu=tunnel,
                shaft_tu=shaft,
                break_block=block,
            )
        )

    # 只保留密度非零的段——零密度段要挖无穷远，不是候选。
    result.sections = [section for section in result.sections if section.volume_density > 0]
    if not result.sections:
        result.assumptions.append("所有纵段密度为零，该群系没有此方块")
        return result

    result.assumptions.append(
        f"到达该层按「从 y={surface_y} 挖竖井」计；无洞穴数据，结果偏保守（上界）"
    )
    if auto_block:
        detail = "/".join(
            f"{block}={mining_facts.break_seconds(block, material=UNDERGROUND_MINING_MATERIAL):.2f}s"
            for block in sorted(used_blocks)
        )
        result.assumptions.append(f"破坏方块按层位自动选（{detail}，铁镐）")
    else:
        result.assumptions.append(
            f"破坏方块按 {break_block}（"
            f"{mining_facts.break_seconds(break_block, material=UNDERGROUND_MINING_MATERIAL):.2f}s/块）计"
        )
    if entries_per_block != 1.0:
        result.assumptions.append(f"每块目标方块掉 {entries_per_block} 个物品")
    return result


def merge_across_biomes(rows) -> tuple[dict[str, dict], int] | None:
    """把同一方块在各群系的采样按等效区块加权合并成一份「就地挖」的纵段数据。

    为什么要这一步：**绝大多数矿石的生成与群系无关**。实测 `ore_density` 里
    19 种矿，只有绿宝石（最高/中位 180×）、恶地金矿（7.6×）、溶洞铜（2.8×）
    是真的群系特异，其余 15 种在 54 个群系之间的差异都在 2 倍以内——那是
    采样方差，不是机制。

    按群系采样只是采集器的切法。拿这些行去 `min()`，等于同时做错两件事：
    系统性挑选采样噪声的高端（winner's curse），以及隐含「可以零成本出现在
    那个群系」。合并成一条代表「随便站在哪挖」的密度，才是可辩护的基准。

    返回 `(sections, total_blocks)`；没有可用采样时返回 `None`。
    `sections` 的 `per_chunk` 是「方块总数 ÷ 等效区块总数」。
    """
    total_chunks = 0.0
    total_blocks = 0
    per_section: dict[str, dict] = {}
    for row in rows:
        value = row.value
        chunks = value.get("equivalent_chunks")
        if not isinstance(chunks, (int, float)) or chunks <= 0:
            continue
        total_chunks += float(chunks)
        blocks = value.get("total_blocks")
        if isinstance(blocks, int):
            total_blocks += blocks
        for key, cell in (value.get("by_section") or {}).items():
            count = cell.get("count")
            if not isinstance(count, (int, float)):
                continue
            slot = per_section.setdefault(key, {"y_range": cell.get("y_range"), "count": 0.0})
            slot["count"] += float(count)
    if total_chunks <= 0 or not per_section:
        return None
    sections = {
        key: {"y_range": slot["y_range"], "per_chunk": slot["count"] / total_chunks}
        for key, slot in per_section.items()
    }
    return sections, total_blocks


def estimate_from_row(
    row,
    *,
    target_items: float = 1.0,
    surface_y: int | None = None,
    break_block: str | None = None,
    entries_per_block: float = 1.0,
    dimension: str | None = None,
) -> MiningEstimate:
    """从一条 `ore_density` / `block_density` 统计行求代价。

    `dimension` 缺省取行自带的维度，用来决定围岩类型与地表高度。
    """
    value = row.value
    estimate_result = estimate(
        biome=row.biome,
        subject=row.subject,
        sections=value.get("by_section") or {},
        target_items=target_items,
        surface_y=surface_y,
        dimension=dimension or getattr(row, "dimension", None) or "minecraft:overworld",
        break_block=break_block,
        entries_per_block=entries_per_block,
    )
    if isinstance(value.get("total_blocks"), int):
        estimate_result.sample_blocks = value["total_blocks"]
    if isinstance(value.get("reliable"), bool):
        estimate_result.chunk_reliable = value["reliable"]

    # 样本量判据用方块数：一个只覆盖少量区块的群系也可能数到上千块矿，
    # 那时密度估得住的；反之 2 块的群系区块再多也没意义。
    trusted = estimate_result.density_trusted
    if trusted is False:
        estimate_result.assumptions.append(
            f"只数到 {estimate_result.sample_blocks} 块（< {MIN_DENSITY_BLOCKS}），"
            "密度样本不足，代价仅供参考"
        )
    return estimate_result
