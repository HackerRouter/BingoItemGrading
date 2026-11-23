"""斑块与岩浆：成片生成的资源怎么到达、装几批。"""

from __future__ import annotations

import math

from bingo_grading import gamedata, mining_facts, units
from bingo_grading.mining import CHUNK_FOOTPRINT, shaft_cost, surrounding_block, surface_y_for
from .model import CaseError, LAVA_LAKE_SETS, PatchSource, Sourced

class PatchesMixin:
    def patch_access_cost(
        self, subject: str, *, dimension: str | None = None
    ) -> tuple[Sourced | None, Sourced | None]:
        """地下**成片**资源最便宜的那一段的到达成本。

        只是 `patch_sources` 的第一条。要「主备两条竞争」请直接用
        `patch_sources`——每一段岩浆湖都是一条独立来源。
        """
        sources = self.patch_sources(subject, dimension=dimension)
        if not sources:
            return None, None
        best = sources[0]
        return (
            Sourced(best.cost_tu, "block_density", best.detail),
            Sourced(best.share, "block_density", f"{subject} 体积占比"),
        )


    def lake_source(
        self,
        subject: str,
        *,
        dimension: str | None = None,
    ) -> PatchSource | None:
        """成湖资源（地表岩浆湖）：按**实测的湖间距 + 湖的容量**定价。

        以前岩浆只有一条口径：把 `block_density[lava]` 的每区块块数当成
        均匀洒开的散点。那个口径会算出「沿地下矿道走 145 格就碰到一片
        50 块的连片岩浆」——两件事都不成立：浅层岩浆根本不是连片的，
        而且地表湖根本不用挖下去。

        worldgen 采集器其实**量过**这件事，只是这份数据一直没被读过：
        `structure_density[minecraft:surface_lava_lake]` 给了
        `expected_nearest_distance`（最近一处多远）、`mean_size`（每湖多大）、
        `density_per_1000_chunks`。于是成本就是「跑到最近的湖」：

        代价 = `travel(distance, underground=False)`，**没有竖井项**。
        容量 = `mean_size / batch` 批，一湖够装几批。

        湖在地表，`expected_nearest_distance` 本来就是地表跑图距离，所以
        这里用 1× 系数而不是地下的 2×——这正是它比纵段口径便宜三成的原因。
        """
        structure = LAVA_LAKE_SETS.get(subject)
        if structure is None:
            return None
        dimension = dimension or self.dimension
        for row in self.store.rows.values():
            if row.stat_type != "structure_density":
                continue
            if row.subject != structure or row.dimension != dimension:
                continue
            value = row.value
            distance = value.get("expected_nearest_distance")
            size = value.get("mean_size")
            if not isinstance(distance, (int, float)) or not distance > 0:
                continue
            if not isinstance(size, (int, float)) or not size > 0:
                continue
            per_k_chunks = value.get("density_per_1000_chunks")
            per_chunk = (
                float(size) * float(per_k_chunks) / 1000.0
                if isinstance(per_k_chunks, (int, float))
                else 0.0
            )
            run = self.travel(float(distance), underground=False)
            blocks = float(size)
            return PatchSource(
                subject=subject,
                y_range=(0, 0),
                per_chunk=per_chunk,
                share=per_chunk / CHUNK_FOOTPRINT if per_chunk > 0 else 0.0,
                depth=0,
                horizontal=float(distance),
                shaft_tu=0.0,
                travel_tu=run.value,
                cost_tu=run.value,
                blocks_per_patch=blocks,
                detail=(
                    f"{subject} 地表岩浆湖：最近 {distance:.0f} 格"
                    f"（{row.provenance}），每湖约 {size:.0f} 块"
                ),
                where=f"跑图 {distance:.0f} 格到最近的岩浆湖",
                kind="lake",
            )
        return None


    def patch_sources(
        self,
        subject: str,
        *,
        dimension: str | None = None,
        blocks_per_patch: float | None = None,
    ) -> list[PatchSource]:
        """地下**成片**资源的每一段一个来源，按到达成本升序。

        与 `mining` 的区别是「要多少块」这件事不存在：

        - `mining` 算的是散点矿——挖穿 `k / 体积密度` 个方块才碰上 k 块；
        - 成片资源的统计单位本来就是**连续块**，到达一片就够用（一片几十块），
          所以只要算「到那儿」。

        代价 = 挖竖井到该纵段 + 沿矿道走到第一片。水平距离按**片密度**估：
        一片 `blocks_per_patch` 块、每区块 `per_chunk` 块，则每
        `blocks_per_patch / per_chunk` 个区块有一片；最近邻期望取
        `0.5 / sqrt(片密度) × 16` 格。

        竖向按段算正是「主备两条竞争」的来源：浅段离地表近但岩浆稀（走很远才
        有一片），深段要挖很久但岩浆密（出门就有）。两段的成本与容量一起进
        供给曲线，先用便宜的，用满再换下一段。

        这个估法假设岩浆片位置独立同分布，是一片**上界**的近似；实际片更集中时
        真值更小。调用方应把这一点写进 `assumptions`。

        **有实测湖间距的资源优先走 `lake_source`**：岩浆湖是 worldgen 采集器
        直接量过的 feature（最近一处多远、每湖多大），比「把方块密度当均匀
        散点」可信得多。只有在没有湖数据时才退回下面的纵段散点口径。
        """
        dimension = dimension or self.dimension
        lake = self.lake_source(subject, dimension=dimension)
        if lake is not None:
            return [lake]
        # 散点兜底：走到这里说明**没有成湖数据**。以前这里有个
        # `gamedata.LAVA_BLOCKS_PER_PATCH = 50` 的默认值，那是拍的——而 worldgen
        # 采集器本来就量过每湖块数（`mean_size`），正常情况在 `lake_source`
        # 就返回了。真缺湖数据时拒绝用猜的数字继续估价，由调用方显式给值。
        if blocks_per_patch is None:
            raise CaseError(
                f"{subject} 没有成湖数据（structure_density 里缺这一组），"
                "且调用方没显式给每片块数：拒绝用默认值继续估价"
            )
        if not blocks_per_patch > 0:
            raise CaseError(f"一片的块数必须为正：{blocks_per_patch}")
        rows = [
            row
            for row in self.store.rows.values()
            if row.stat_type in ("block_density", "ore_density")
            and row.subject == subject
            and row.dimension == dimension
        ]
        if not rows:
            return []
        # 优先维度级行（不分群系）：`by_section` 才是全维度口径。
        scoped = [row for row in rows if not row.biome] or rows
        best_row = max(scoped, key=lambda row: row.value.get("per_chunk_density") or 0.0)
        by_section = best_row.value.get("by_section") or {}

        out: list[PatchSource] = []
        seen: set[tuple[int, int]] = set()
        for section in by_section.values():
            y_range = tuple(section.get("y_range") or ())
            if len(y_range) != 2:
                continue
            y_low, y_high = int(y_range[0]), int(y_range[1])
            if (y_low, y_high) in seen:
                continue
            seen.add((y_low, y_high))
            per_chunk = float(section.get("per_chunk") or 0.0)
            if per_chunk <= 0:
                continue
            height = y_high - y_low + 1
            share = per_chunk / (CHUNK_FOOTPRINT * height)
            patches_per_chunk = per_chunk / blocks_per_patch
            horizontal = 0.5 / math.sqrt(patches_per_chunk) * 16.0
            depth = max(0, surface_y_for(dimension) - y_high)
            block = surrounding_block(y_high, dimension)
            # 与 `mining.shaft_cost` 同一口径（含截面），不在案例层重写公式。
            shaft_tu = shaft_cost(
                surface_y_for(dimension),
                y_high,
                break_seconds=mining_facts.break_seconds(
                    block, material=gamedata.UNDERGROUND_MINING_MATERIAL
                ),
            )
            travel_tu = (
                horizontal * units.TU_PER_BLOCK_RUN * gamedata.UNDERGROUND_MOVE_FACTOR
            )
            out.append(
                PatchSource(
                    subject=subject,
                    y_range=(y_low, y_high),
                    per_chunk=per_chunk,
                    share=share,
                    depth=depth,
                    horizontal=horizontal,
                    shaft_tu=shaft_tu,
                    travel_tu=travel_tu,
                    cost_tu=shaft_tu + travel_tu,
                    blocks_per_patch=blocks_per_patch,
                    detail=(
                        f"{subject} y{y_low}~{y_high}：每区块 {per_chunk:.2f} 块，"
                        f"一片约 {blocks_per_patch:g} 块 → 每区块 "
                        f"{patches_per_chunk:.3f} 片；挖竖井 {depth} 格花 "
                        f"{shaft_tu:.2f} TU + 沿矿道 {horizontal:.0f} 格花 "
                        f"{travel_tu:.2f} TU（片间距按独立同分布估，是上界）"
                    ),
                    where=(
                        f"下挖到 y{y_high}，沿矿道走 {horizontal:.0f} 格找第一片"
                        f"（{depth} 格竖井）"
                    ),
                    kind="shaft",
                )
            )
        out.sort(key=lambda item: (item.cost_tu, -item.y_range[1]))
        return out
