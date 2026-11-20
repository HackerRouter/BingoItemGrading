"""暴露与纵段：六面邻接份额、剖面填充、洞穴体积。"""

from __future__ import annotations

import math

from bingo_grading.mining import surface_y_for
from .model import BlockExposure, Sourced

class ExposureMixin:
    # ---------------------------------------------------------------- 挖掘

    # 敞开判据的阈值：段内**扣除水之后**仍以实心方块为主就算埋着。
    # 实测地表/水下露头 6%–28%、地下 89%–99%，断层很宽。
    OPEN_SECTION_FILL = 0.5


    def block_exposure(
        self, block: str, *, dimension: str | None = None
    ) -> tuple[BlockExposure, Sourced] | None:
        """方块的 6 面暴露四分：天空 / 洞穴 / 水 / 埋着。

        这是上游 `cave-exposure` 的实测值，比「段填充率」精确一档：
        段填充率只知道「这段整体敞开不敞开」，这里知道**方块自己贴着什么**。

        实测几例（主世界）：`bamboo` 天空 96.4%、`sugar_cane` 99.9%、
        `oak_log` 天空 44.6% + 洞穴 8.0%、`sand` 水下 42.2% + 天空 9.3%、
        `clay` 水 4.8% + 洞穴 6.3%（这个包的粘土主要在深处）。

        没有该方块的暴露行时返回 `None`（上游只统计名单内的方块），
        调用方不能默认当敞开。
        """
        dimension = dimension or self.dimension
        for row in self.store.rows.values():
            if (
                row.stat_type == "block_exposure"
                and row.subject == block
                and row.dimension == dimension
            ):
                value = row.value
                exposure = BlockExposure(
                    per_chunk=float(value.get("per_chunk_density") or 0.0),
                    sky=float(value.get("sky_air_share") or 0.0),
                    cave=float(value.get("cave_air_share") or 0.0),
                    water=float(value.get("water_share") or 0.0),
                    buried=float(value.get("buried_share") or 0.0),
                )
                detail = (
                    f"{block} 6 面暴露：天空 {exposure.sky:.2%} + 水 "
                    f"{exposure.water:.2%} + 洞穴 {exposure.cave:.2%}，"
                    f"埋着 {exposure.buried:.2%}（{row.provenance}）"
                )
                return exposure, Sourced(
                    exposure.walkable, "block_exposure:sky+water", detail
                )
        return None


    def _section_fills(self, dimension: str) -> dict[int, dict[str, float]]:
        """该维度每个纵段的实心占比：`{起始y: {"fill": 含流, "dry": 扣水}}`。

        两个数各有用途，不能混：

        - `dry`（扣水与岩浆）判断「这段敞开不敞开」——水下露头也是走得到的；
        - `fill`（含流）算「洞穴体积」——地下水不是可通行空间，扣掉水会凭空
          多出几倍的「洞穴」（实测 y48~63 段从 145 格虚增到 1603 格）。
        """
        for row in self.store.rows.values():
            if (
                row.stat_type == "section_fill"
                and row.dimension == dimension
                and not row.biome
            ):
                fills: dict[int, dict[str, float]] = {}
                for key, cell in (row.value.get("sections") or {}).items():
                    try:
                        y = int(key)
                    except (TypeError, ValueError):
                        continue
                    fill = cell.get("fill")
                    if fill is None:
                        continue
                    dry = cell.get("fill_dry")
                    fills[y] = {
                        "fill": float(fill),
                        "dry": float(fill) if dry is None else float(dry),
                    }
                return fills
        return {}


    def block_openness(
        self, block: str, *, dimension: str | None = None
    ) -> tuple[float, Sourced] | None:
        """方块主段**上方那一段**的实心占比（已扣掉水与岩浆），以及出处。

        用来判断该方块主要暴露在外面（走得到）还是被埋着（得挖下去）。
        看的是**上方**而不是本段：海底沙所在的段 40% 是水、实心占比 96%，
        按本段判会把水下露头误判成埋着；它上面那一段（海面以上）才是 27%。

        取**主段**（该方块数量最多的纵段）而不是最高段——最高段常常只占
        总量的 0.0%（零星露头），用它判会把基本埋着的方块当成地表。

        返回 `None` 表示没有纵段数据，调用方不能默认当敞开。
        """
        dimension = dimension or self.dimension
        rows = [
            row
            for row in self.store.rows.values()
            if row.stat_type == "block_density"
            and row.subject == block
            and row.dimension == dimension
        ]
        if not rows:
            return None
        scoped = [row for row in rows if not row.biome] or rows
        best = max(scoped, key=lambda row: row.value.get("per_chunk_density") or 0.0)
        sections = list((best.value.get("by_section") or {}).values())
        if not sections:
            return None
        peak = max(sections, key=lambda section: float(section.get("per_chunk") or 0.0))
        y_range = tuple(peak.get("y_range") or ())
        if len(y_range) != 2:
            return None
        peak_y = int(y_range[0])
        fills = self._section_fills(dimension)
        if fills:
            above = fills.get(peak_y + 16)
            if above is not None:
                value = above["dry"]
                detail = (
                    f"{block} 主段 y{peak_y}~{y_range[1]}，其上 y{peak_y + 16}~"
                    f"{peak_y + 31} 实心占比 {value:.1%}（已扣水与岩浆；"
                    f"{best.provenance}）"
                )
                return value, Sourced(value, "section_fill:fill_dry", detail)
            # 主段已在最高段：上面没有东西了，必然是敞开的
            detail = f"{block} 主段 y{peak_y}~{y_range[1]} 已是最顶层（{best.provenance}）"
            return 0.0, Sourced(0.0, "section_fill:top", detail)
        # 没有段表（旧快照）：退回方块自己那一格的段填充率，口径差一档但比没有好
        cell_fill = peak.get("section_fill")
        if cell_fill is None:
            return None
        detail = (
            f"{block} 主段 y{peak_y}~{y_range[1]} 本段实心占比 {float(cell_fill):.1%}"
            f"（无段表，未看上方段；{best.provenance}）"
        )
        return float(cell_fill), Sourced(
            float(cell_fill), "block_density:section_fill", detail
        )


    # ---------------------------------------------------------------- 结构

    def _open_sections(
        self, value: dict, *, dimension: str
    ) -> list[tuple[int, dict]]:
        """该方块「上方段敞开」的那些纵段，也就是**地表可得**的部分。

        `clay` 全高 97 块/区块，但露在河床的只有 2.6 块（2.7%）——
        拿全高当「走过去就能捡」会把走动距离低估几十倍。
        """
        sections = list((value.get("by_section") or {}).items())
        if not sections:
            return []
        fills = self._section_fills(dimension)
        if not fills:
            # 没有段表（旧快照）：分不出地表与地下，只能全算
            return [(int(key), section) for key, section in sections]
        out: list[tuple[int, dict]] = []
        for key, section in sections:
            y_range = section.get("y_range") or ()
            if len(y_range) != 2:
                continue
            y = int(y_range[0])
            above = fills.get(y + 16)
            if above is None or above < self.OPEN_SECTION_FILL:
                out.append((y, section))
        return out


    # 地下洞穴通道的平均截面（格²）。**只用于 `cave_volume_per_chunk` 的体积
    # 换算已废弃**——结构搜索已改用体积占比（`structure_search_cost`），不依赖它。
    # 保留原因：`cave_volume_per_chunk` 仍被诊断脚本用来粗估洞穴通道长度。
    #
    # 「体积 ÷ 截面」对大厅必错：大厅体积大、玩家穿过去只要几十格，除法会把
    # 一个大厅算成几百格通道。所以任何依赖它的结论都只当量级参考。
    CAVE_CROSS_SECTION = 6.0


    def cave_volume_per_chunk(
        self,
        *,
        dimension: str | None = None,
        top_y: int | None = None,
        bottom_y: int | None = None,
    ) -> tuple[float, Sourced] | None:
        """每区块在指定高度带内的空隙体积（格³）。

        = Σ_段 (1 - `fill`) × 4096，只算段底不低于 `bottom_y`、
        段顶不高于 `top_y` 的段。这里用的是**含水**的 `fill`：
        地下水与岩浆不是可通行空间，用扣水的 `fill_dry` 会把它们
        算成洞穴，实测能把体积虚增到 4 倍（y48~63 段 145 → 1603 格³）。

        `bottom_y` 用于排除结构不会生成的高度带（地牢不在深板岩层）。
        """
        dimension = dimension or self.dimension
        top = surface_y_for(dimension) if top_y is None else top_y
        bottom = -math.inf if bottom_y is None else bottom_y
        fills = self._section_fills(dimension)
        if not fills:
            return None, None
        volume = 0.0
        counted: list[int] = []
        for y, cell in fills.items():
            if y + 15 > top or y < bottom:
                continue
            volume += max(0.0, 1.0 - cell["fill"]) * 4096.0
            counted.append(y)
        if not counted:
            return None, None
        span = f"y{counted[0]}~{counted[-1] + 15}"
        detail = (
            f"{span} 的 {len(counted)} 个纵段空隙合计 {volume:.0f} 格³/区块"
            f"（1 - fill，含流体的段不把流体算作空隙）"
        )
        return volume, Sourced(volume, "section_fill:1-fill", detail)


    def underground_volume_per_chunk(
        self,
        *,
        dimension: str | None = None,
        top_y: int | None = None,
        bottom_y: int | None = None,
    ) -> int:
        """每区块在指定高度带内的完整体积（格³，不分实心/空隙）。"""
        dimension = dimension or self.dimension
        top = surface_y_for(dimension) if top_y is None else top_y
        bottom = -math.inf if bottom_y is None else bottom_y
        counted = [
            y
            for y in self._section_fills(dimension)
            if y + 15 <= top and y >= bottom
        ]
        return len(counted) * 4096
