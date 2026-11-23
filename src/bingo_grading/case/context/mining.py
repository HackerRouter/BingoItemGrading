"""挖矿定价：地表 / 洞穴 / 矿脉三条采集模型的取数与换算。"""

from __future__ import annotations

import statistics

from bingo_grading import gamedata, mining_facts, units
from bingo_grading.mining import BIOME_SPECIFIC_ORES, MiningEstimate, MiningError, estimate as estimate_sections, estimate_from_row, merge_across_biomes, surface_y_for
from .model import Sourced, _find_distance

class MiningMixin:
    def mining(
        self,
        subject: str,
        *,
        dimension: str | None = None,
        target_items: float = 1.0,
        entries_per_block: float = 1.0,
    ) -> tuple[MiningEstimate | None, Sourced | None]:
        """某方块的最优挖掘代价（跨群系取最小）。

        `dimension` 缺省用本上下文的维度；跨维度路线显式传入。

        只在方块数够多的群系里挑最优（`density_trusted`），判据是数到的方块数
        而不是区块数：密度是 `方块数 / 等效区块数`，误差由计数主导，
        覆盖区块少但数到上千块矿的群系依然可信。

        全都不够时退回全部，并在出处里标出这一点。
        """
        dimension = dimension or self.dimension
        cache_key = (subject, dimension, target_items, entries_per_block)
        if cache_key in self._mining_cache:
            return self._mining_cache[cache_key]
        rows = [
            row
            for stat_type in ("ore_density", "block_density")
            for row in self.store.of(stat_type, subject)
            if row.dimension == dimension
        ]
        if not rows:
            self._mining_cache[cache_key] = (None, None)
            return None, None
        # 「就地挖」：密度取所有群系合并采样。绝大多数矿石的生成与群系无关，
        # 拿 54 个群系的密度去挑最小的那个只是在挑采样噪声的高端。
        merged = merge_across_biomes(rows)
        local: tuple[MiningEstimate, float] | None = None
        if merged is not None:
            sections, sample = merged
            try:
                built = estimate_sections(
                    biome="",
                    subject=subject,
                    sections=sections,
                    target_items=target_items,
                    dimension=dimension,
                    entries_per_block=entries_per_block,
                )
            except MiningError:
                built = None
            if built is not None and built.sample_blocks is None:
                built.sample_blocks = sample or None
            if built is not None:
                built.assumptions.append("就地挖：密度按所有群系合并采样，不含跑图")
            if built is not None and built.cost_tu is not None:
                local = (built, 0.0)

        estimates = []
        is_ore = any(row.stat_type == "ore_density" for row in rows)
        # 矿石默认不许挑群系。只有两种情况例外：真按群系过滤的那几种
        # （见 `mining.BIOME_SPECIFIC_ORES`），或者「就地挖」算不出来
        # （下界矿石的 `ore_density` 不带 `by_section`，合并会失败）——
        # 后者不能把整条路判死，只能退回逐群系。
        allow_biome = (not is_ore) or subject in BIOME_SPECIFIC_ORES or local is None
        for row in rows:
            if not allow_biome:
                break
            try:
                estimate = estimate_from_row(
                    row,
                    target_items=target_items,
                    entries_per_block=entries_per_block,
                    dimension=dimension,
                )
            except MiningError:
                continue
            if estimate.cost_tu is None:
                continue
            # 「专门去那个群系挖」要付路费。原先这里只按挖掘时间排序，
            # 等于假定玩家能零成本出现在密度最高的群系——`iron_ore` 因此
            # 选了 `ice_spikes`、`coal_ore` 选了 `frozen_peaks`。
            # 只有矿石算路费：`block_density` 的「找方块」成本另有
            # `block_search_cost()` 那条路，不在这里重复计。
            travel = 0.0
            if row.stat_type == "ore_density" and row.biome:
                found = self.biome_search_cost(row.biome)
                if found is not None:
                    travel = found[0].value
            estimates.append((estimate, travel))
        if local is not None:
            estimates.append(local)

        if not estimates:
            self._mining_cache[cache_key] = (None, None)
            return None, None

        trusted = [item for item in estimates if item[0].density_trusted]
        pool = trusted or estimates
        best, travel = min(pool, key=lambda item: item[0].cost_tu + item[1])
        section = best.best
        where = "就地挖" if not best.biome else f"{best.biome}（路费 {travel:.2f} TU）"
        detail = (
            f"{where} y{section.y_range[0]}~{section.y_range[1]} "
            f"{section.break_block}（{len(pool)}/{len(estimates)} 个候选参与比较，"
            f"{best.sample_blocks} 块样本）"
        )
        if not trusted:
            detail += "，全部样本不足"
        total = best.cost_tu + travel
        result = (best, Sourced(total, "mining", detail))
        self._mining_cache[cache_key] = result
        return result


    def surface_block_parts(
        self,
        block: str,
        *,
        dimension: str | None = None,
        break_block: str | None = None,
        find_distance: float | None = None,
    ) -> tuple[Sourced, Sourced, Sourced] | None:
        """露头方块拆成（每块成本, 找首片成本, 地表密度）。

        拆开的目的是：**找首片只付一次**。原来把它摊进单价里，捡 64 个就要付
        64 次「走到河边」的钱。`mine_vein` 的竖井也是这么处理的（进 `overhead`）。

        找首片是「密度统计只给全图平均、不告诉玩家最近的河在哪」的补偿，
        未显式传入时由 `_find_distance` 按实测密度反推（泊松最近邻 `8/√ρ`）。

        **可得密度只用实测暴露**：`block_exposure` 给出该方块贴天空/水的比例，
        乘上全高密度就是「走过去能捡到的量」。没有暴露数据就不给地表来源——
        段填充率算不出「方块自己是否露着」：`iron_ore` 在 y48~63 段有 1.7 块/区块、
        上方段是空气，按段级数据会算出 1.07 TU/个，实际要挖 14 TU。
        实测 `clay` 天空 0.009% + 水 4.8%、`sand` 天空 9.3% + 水 42.2%，
        这类水下/地表露头是真能捡的。
        """
        dimension = dimension or self.dimension
        rows = [
            row
            for row in self.store.of("block_density", block)
            if row.dimension == dimension
        ]
        if not rows:
            return None  # type: ignore[return-value]
        best = max(rows, key=lambda row: row.value.get("per_chunk_density") or 0.0)
        total_density = best.value.get("per_chunk_density") or 0.0
        if total_density <= 0:
            return None  # type: ignore[return-value]
        exposure = self.block_exposure(block, dimension=dimension)
        if exposure is None:
            return None  # type: ignore[return-value]
        walkable = exposure[0].walkable
        if walkable <= 0:
            return None  # type: ignore[return-value]
        density = total_density * walkable
        density_detail = (
            f"{block} 贴天空/水 {walkable:.2%} × 每区块 {total_density:.2f}"
            f" = {density:.2f} 块可捡（{exposure[1].detail}）"
        )

        break_seconds = mining_facts.break_seconds(break_block or "dirt")
        per_block = (
            (16.0 / density) * units.TU_PER_BLOCK_RUN
            + break_seconds / units.SECONDS_PER_TU
        )
        if find_distance is None:
            find_distance = _find_distance(density)
        find = find_distance * units.TU_PER_BLOCK_RUN
        share = density / total_density if total_density > 0 else 1.0
        return (
            Sourced(
                per_block,
                "block_density",
                f"{block} 每块：带内走 {16.0 / density:.1f} 格 + 挖 "
                f"{break_seconds:.2f} 秒",
            ),
            Sourced(
                find,
                "block_density",
                f"{block} 找到首片 {find_distance:.0f} 格（密度统计是全图平均，"
                f"不告诉最近的河在哪）",
            ),
            Sourced(
                density,
                "block_density",
                f"{density_detail}；占全高 {share:.1%}",
            ),
        )


    def cave_block_parts(
        self,
        block: str,
        *,
        dimension: str | None = None,
        break_block: str | None = None,
        find_distance: float | None = None,
    ) -> tuple[Sourced, Sourced, Sourced] | None:
        """洞穴暴露的方块拆成（每块成本, 到达成本, 洞穴密度）。

        与 `surface_block_parts` 的区别：这些方块看得见，但在地下——要走到洞口、
        沿洞穴通道下潜，然后走过去挖。也不用像 `mine_vein` 那样盲挖岩层
        （`tunnel_tu` 那部分按「1/ρ 个方块全挖掉」算，洞穴里根本不用挖）。

        到达成本 = 走到洞口 `find_distance` 格 + 沿洞穴下潜 `depth` 格
        （下潜按 `UNDERGROUND_MOVE_FACTOR` 折算，不是挖竖井——竖井要挖掉
        `swath` 倍方块，洞穴通道是现成的）。

        **矿石走另一条分支**：`block_exposure` 的方块名单里没有矿石（51 个全是
        原木、沙砾、陶瓦这类），所以下面这条通用路径对矿石永远返回 `None`，
        矿石因此只有「盲挖矿道」一条路。但 `ore_exposure` 给了
        `avgAirExposed`——**每区块暴露在空气中的矿数**（含洞穴与天空），
        那正是「沿洞穴走能捡到多少」，直接就能用。
        """
        dimension = dimension or self.dimension
        ore_parts = self._ore_cave_parts(
            block,
            dimension,
            break_block=break_block,
            find_distance=find_distance,
        )
        if ore_parts is not None:
            return ore_parts
        exposure = self.block_exposure(block, dimension=dimension)
        if exposure is None:
            return None  # type: ignore[return-value]
        cave_share = exposure[0].cave
        if cave_share <= 0:
            return None  # type: ignore[return-value]
        dimension = dimension or self.dimension
        rows = [
            row
            for row in self.store.of("block_density", block)
            if row.dimension == dimension
        ]
        if not rows:
            return None  # type: ignore[return-value]
        best = max(rows, key=lambda row: row.value.get("per_chunk_density") or 0.0)
        total_density = best.value.get("per_chunk_density") or 0.0
        density = total_density * cave_share
        if density <= 0:
            return None  # type: ignore[return-value]
        sections = list((best.value.get("by_section") or {}).values())
        peak = (
            max(sections, key=lambda section: float(section.get("per_chunk") or 0.0))
            if sections
            else None
        )
        depth = 0
        if peak is not None:
            y_range = peak.get("y_range") or ()
            if len(y_range) == 2:
                depth = max(
                    0, surface_y_for(dimension) - int(y_range[1])
                )
        if find_distance is None:
            find_distance = _find_distance(density)
        approach = (
            find_distance * units.TU_PER_BLOCK_RUN
            + depth * units.TU_PER_BLOCK_RUN * gamedata.UNDERGROUND_MOVE_FACTOR
        )
        break_seconds = mining_facts.break_seconds(
            break_block or "dirt", material=gamedata.UNDERGROUND_MINING_MATERIAL
        )
        per_block = (
            (16.0 / density) * units.TU_PER_BLOCK_RUN
            + break_seconds / units.SECONDS_PER_TU
        )
        return (
            Sourced(
                per_block,
                "block_exposure:cave",
                f"{block} 洞穴内每块：走 {16.0 / density:.1f} 格 + 挖 "
                f"{break_seconds:.2f} 秒",
            ),
            Sourced(
                approach,
                "block_exposure:cave",
                f"{block} 到洞穴：走到洞口 {find_distance:.0f} 格 + 下潜 {depth} 格"
                f"（洞穴通道现成，不挖竖井）",
            ),
            Sourced(
                density,
                "block_exposure:cave",
                f"{block} 洞穴可及 {cave_share:.2%} × 每区块 {total_density:.2f}"
                f" = {density:.2f} 块（{exposure[1].detail}）",
            ),
        )


    def _ore_cave_parts(
        self,
        block: str,
        dimension: str,
        *,
        break_block: str | None,
        find_distance: float | None,
    ) -> tuple[Sourced, Sourced, Sourced] | None:
        """矿石的「沿洞穴捡」拆分：`(每块成本, 到达成本, 暴露密度)`。

        数据来源是 `ore_exposure` 的 `avgAirExposed`——每区块暴露在空气中的
        矿方块数。这个数此前**一个都没被读过**：`sources/exposure.py` 只用
        `stat_type in ("ore_density","ore_exposure")` 判「这是矿石 → 算地下」，
        数值本身从未参与定价，所以 822 行暴露统计一直是白采集的。

        取哪个群系：真按群系过滤的那几种（`BIOME_SPECIFIC_ORES`）取暴露最多的
        群系，其余取**中位数**——与 `mining()` 的「就地挖」同一套理由，
        拿 54 个群系的暴露数去挑最大值只是在挑采样噪声的高端。
        """
        rows = [
            row
            for row in self.store.of("ore_exposure", block)
            if row.dimension == dimension
        ]
        if not rows:
            return None
        samples = [
            (float(row.value.get("air_exposed") or 0.0), row) for row in rows
        ]
        samples = [(value, row) for value, row in samples if value > 0]
        if not samples:
            return None
        if block in BIOME_SPECIFIC_ORES:
            exposed, row = max(samples, key=lambda item: item[0])
            detail = f"{row.biome} 暴露最多"
        else:
            exposed = statistics.median([value for value, _ in samples])
            detail = f"{len(samples)} 个群系的暴露数中位"
        if exposed <= 0:
            return None

        # 下潜深度：该矿密度最高那一段的顶端。
        depth = 0
        sections: list[dict] = []
        for row in self.store.of("ore_density", block):
            if row.dimension != dimension:
                continue
            sections.extend((row.value.get("by_section") or {}).values())
        if sections:
            peak = max(sections, key=lambda cell: float(cell.get("per_chunk") or 0.0))
            y_range = peak.get("y_range") or ()
            if len(y_range) == 2:
                depth = max(0, surface_y_for(dimension) - int(y_range[1]))

        if find_distance is None:
            find_distance = _find_distance(exposed)
        approach = (
            find_distance * units.TU_PER_BLOCK_RUN
            + depth * units.TU_PER_BLOCK_RUN * gamedata.UNDERGROUND_MOVE_FACTOR
        )
        break_seconds = mining_facts.break_seconds(
            break_block or "stone", material=gamedata.UNDERGROUND_MINING_MATERIAL
        )
        per_block = (
            (16.0 / exposed) * units.TU_PER_BLOCK_RUN
            + break_seconds / units.SECONDS_PER_TU
        )
        return (
            Sourced(
                per_block,
                "ore_exposure:cave",
                f"{block} 暴露矿每块：走 {16.0 / exposed:.1f} 格 + 挖 "
                f"{break_seconds:.2f} 秒",
            ),
            Sourced(
                approach,
                "ore_exposure:cave",
                f"{block} 到洞穴：走到洞口 {find_distance:.0f} 格 + 下潜 {depth} 格"
                f"（洞穴通道现成，不挖竖井）",
            ),
            Sourced(
                exposed,
                "ore_exposure:cave",
                f"{block} 每区块暴露 {exposed:.2f} 块（{detail}；含天空与水，"
                f"所以是 caving 的上界）",
            ),
        )


    def surface_block_cost(
        self,
        block: str,
        count: float,
        *,
        dimension: str | None = None,
        break_block: str | None = None,
        find_distance: float | None = None,
    ) -> tuple[Sourced | None, Sourced | None]:
        """露头可见方块的采集成本（粘土、沙子这类）。

        与 `mining` 的区别：这些方块**露在地表/水下、看得见**，不需要挖矿道去碰。
        用「挖矿道」模型会把成本算高一个数量级——粘土在河里成片躺着，
        挖 2 块只要 0.3 秒，而矿道模型会算出要挖上千个方块。

        代价 = 走到能找到够用量的距离 + 挖掉这些方块的时间。

        走多远由两部分组成：

        - **找到首片资源**：`find_distance` 格。密度统计是**全图平均**，
          它不会告诉玩家「最近的河在哪」。
          不传时由 `_find_distance` 按实测密度反推（泊松最近邻 `8/√ρ`），
          不再用对所有方块一视同仁的常量。
        - **在资源带内走多远**：每区块有 ρ 块，要 `count` 块需覆盖 `count / ρ`
          个区块。取密度最高的那一行（最快能找到的地方）。

        返回 `(代价, 密度出处)`。内部的拆分见 `surface_block_parts`——
        动作层要用「每块 + 找首片一次性」的形式，否则捡多个会重复收找路费。
        """
        parts = self.surface_block_parts(
            block,
            dimension=dimension,
            break_block=break_block,
            find_distance=find_distance,
        )
        if parts is None or parts[0] is None:
            return None, None
        per_block, find, density_source = parts
        total = per_block.value * count + find.value
        return (
            Sourced(
                total,
                "block_density",
                f"{block}：找首片 {find.value:.3f} TU 一次 + 每块 "
                f"{per_block.value:.3f} TU × {count:g}（{density_source.detail}）",
            ),
            density_source,
        )
