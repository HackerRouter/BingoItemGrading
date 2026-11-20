"""统一入口：来源索引 → 动作图。

`bg index sources` 已经把 RA 关系图摊成 `build/<pack>/source_index.jsonl`：
一个物品的每条独立来源一行（3128 行 / 1414 个物品 / 6 类来源）。这个模块
把这些记录**批量**翻译成 `Action`，再沿配方与熔炼链递归补齐原料，产出可以
直接 `solve` 的 `ActionSet`。

分工因此变成：

- 上游图：一个物品**有哪些**来源（数据）；
- 本模块：每条来源**多少钱**（唯一的翻译层）；
- 引擎：在来源之间怎么选（供给曲线、容量、`once` 去重、`race` 并行）。

案例模块只声明「关心哪个目标」，不再手写来源。没接上的记录逐条记进
`GraphActions.uncovered`，不静默丢弃——遗漏必须是可见的。

```python
built = actions.build(ctx, "minecraft:iron_ingot")
solve(built.actionset(), "minecraft:iron_ingot", 1.0)
```

实现按来源族拆在同名子模块里，本文件只做门面。
"""

from __future__ import annotations

from .build import build
from .common import (
    BINDING_PREFIX,
    DIMENSION_ACCESS,
    GADGET_SOURCES,
    GEODE_SOURCES,
    MAX_DEPTH,
    NODE_TABLES,
    NON_STRUCTURE_TABLES,
    RESIN_SOURCES,
    SMELT_SERIALIZERS,
    WANDERING_TRADER,
    WANDERING_TRADER_CAP,
    NodeTable,
    default_index,
)
from .graph import GraphActions
from .transmute import WATER_SOURCE, WATER_SOURCE_ACTION, WEAKEST_TOOL
from .trade import TRADES_PER_LEVEL, TRADE_ALIASES

# 交易规则的白盒测试直接盯这三个函数；放在门面上，测试就不必依赖内部布局。
from .trade import _level_trades, _trade_candidates, _xp_at  # noqa: F401

__all__ = [
    "BINDING_PREFIX",
    "DIMENSION_ACCESS",
    "GADGET_SOURCES",
    "GEODE_SOURCES",
    "GraphActions",
    "MAX_DEPTH",
    "NODE_TABLES",
    "NON_STRUCTURE_TABLES",
    "NodeTable",
    "RESIN_SOURCES",
    "SMELT_SERIALIZERS",
    "TRADES_PER_LEVEL",
    "TRADE_ALIASES",
    "WANDERING_TRADER",
    "WANDERING_TRADER_CAP",
    "WATER_SOURCE",
    "WATER_SOURCE_ACTION",
    "WEAKEST_TOOL",
    "build",
    "default_index",
]
