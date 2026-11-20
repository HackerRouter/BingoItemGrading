"""把世界统计收集侧的产物转成 `world_stat` 行。

收集侧一次运行产出 `stats/<时间戳>/` 目录，每个分析器一个 JSON。本模块只读
这些文件，不重新解析存档。

## 只认 schemaVersion 2

v2 起产物带 `target`（版本/种子/地形包哈希）、结构化 `range`、`units`，且
`result` 按维度嵌套。v1 的 `result` 是扁平对象，维度信息丢失，无法安全导入；
遇到 v1 直接报错，要求用新版采集侧重跑，不做双形态兼容。

## 两套矿石口径不能混

| 分析器 | 统计类型 | 分母 | 语义 |
|---|---|---|---|
| `ore-exposure` | `ore_exposure` | 总区块数 | 顺路能碰到多少（含暴露分解） |
| `biome-ore` | `ore_density` | 该群系等效区块数 | 专程去该群系挖，一个区块有多少 |

`biome-ore` 的 `avgPerChunk` 分母是「地表列数 / 256」，而 `ore-exposure` 的
`avgTotal` 分母是扫描区块数。两者数值接近但语义不同，混用会让「进群系挖矿道」
的代价算错。群系级只讲分布：玩家会专程进该群系挖，暴露不影响代价。

## 抽样精度

`chunks` 写进 `sample_size`；置信度按分母分级，阈值见 `CONFIDENCE_THRESHOLDS`。
采集侧自带的 `reliable`（`chunks >= minChunks`）优先于本侧分级：它表达的是
「这个群系的样本量够不够下结论」，本侧分级只表达「整体样本量大小」。

实现按分析器族拆成子模块；本文件只做门面。
"""

from __future__ import annotations

from .biomes import _autocorr_tier  # noqa: F401  测试直接验证分档
from .model import (
    LAVA_SUBJECT,
    ImportError_,
    ImportResult,
    Target,
    confidence_for,
    guess_minecraft_version,
)
from .reader import import_run, read_target

__all__ = [
    "ImportError_",
    "ImportResult",
    "LAVA_SUBJECT",
    "Target",
    "confidence_for",
    "guess_minecraft_version",
    "import_run",
    "read_target",
]
