"""用 `block_exposure` 的 6 面实测判「该去地表捡还是去地下挖」。

替代 `knowledge/routes.toml` 里那份手写的 `underground_blocks` 清单——
清单只有 5 个矿石加 4 个前缀，`minecraft:iron_ore`（浅层铁矿）根本不在里面，
会被当成地表来源；而 `redstone_ore` 在清单里、`deepslate_redstone_ore` 靠前缀
命中，两者判法本来是两套依据。

改用实测后判据只有一条：**多数方块贴空气或水 → 地表**。实测（主世界）：

| 方块 | 贴空气 | 贴水 | 合计 | 判定 |
|---|---|---|---|---|
| `bamboo` | 96.4% | 0% | 96.4% | 地表 |
| `oak_log` | 52.4% | 0.6% | 53.0% | 地表 |
| `sand` | 9.4% | 42.2% | 51.6% | 地表 |
| `gravel` | 2.7% | 13.4% | 16.1% | 地下 |
| `clay` | 6.3% | 4.8% | 11.1% | 地下 |

没有 exposure 行的方块（上游只统计名单内方块）返回 `None`，调用方退回
`routes.toml` 的清单——不能默认当地表。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExposureRoutes:
    """方块 → 路线（`surface` / `underground`）。"""

    # 「多数贴空气或水」就是地表。与 `OPEN_SECTION_FILL` 同类：
    # 是「过半」这个物理定义的阈值，不是拟合出来的参数。
    SURFACE_SHARE = 0.5

    shares: dict[str, float] = field(default_factory=dict)
    # 判成地表的方块里，靠水而不是空气达成的（水下露头，要潜水）。
    watery: frozenset[str] = frozenset()
    # 上游按「矿」统计的方块（有 `ore_density` / `ore_exposure` 行）：
    # 它们一律算地下。这比 `routes.toml` 的手写清单可靠：那份清单只有
    # 5 个矿石，`iron_ore` / `coal_ore` / `gold_ore` 都被漏成了「地表」。
    ore_blocks: frozenset[str] = frozenset()

    @classmethod
    def from_rows(cls, rows) -> "ExposureRoutes":
        source = rows.values() if isinstance(rows, dict) else rows
        shares: dict[str, float] = {}
        watery: set[str] = set()
        ores: set[str] = set()
        for row in source:
            if row.stat_type in ("ore_density", "ore_exposure"):
                ores.add(row.subject)
            if row.stat_type != "block_exposure":
                continue
            value = row.value
            air = float(value.get("air_exposed_share") or 0.0)
            water = float(value.get("water_share") or 0.0)
            shares[row.subject] = air + water
            if water > air and air + water >= cls.SURFACE_SHARE:
                watery.add(row.subject)
        return cls(
            shares=shares,
            watery=frozenset(watery),
            ore_blocks=frozenset(ores),
        )

    def route_for(self, block: str) -> str | None:
        # 矿石不靠暴露判：地表露头也要挖（且上游只对矿石给了 ore_density）。
        if block in self.ore_blocks:
            return "underground"
        share = self.shares.get(block)
        if share is None:
            return None
        return "surface" if share >= self.SURFACE_SHARE else "underground"

    def __len__(self) -> int:
        return len(self.shares) + len(self.ore_blocks)
