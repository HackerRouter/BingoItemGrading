"""两个 Minecraft 数据项目共用的解析层。

## 为什么单独成立一个包

RecipeAnalysis 与 BingoItemGrading 读的是同一批原版数据包，语法层的判断完全一致：
战利品表的 `condition` / `conditions` 两地方言、`modifier` / `functions` 两套键名、
条目树里哪些类型是容器。两边各写一份，就会出现「一边认这种方言、另一边不认」的分叉。

这里只放**语法还原**：把数据包 JSON 归一成固定形状，不判断语义、不计算概率。
语义（`serializer → station`、`legacy 表的映射`）留在 RecipeAnalysis 的 IR 层，
概率与代价留在 BingoItemGrading 的 `loot/expect.py`。

## 接线方式（临时）

本包物理上只有一份（在 BingoItemGrading 的 `src/mcshared/`）。
RecipeAnalysis 通过 `src/ra/mcshared` junction 以 `ra.mcshared` 引用它。
抽取稳定后可各自独立发布，届时去掉 junction 即可。

## 版本

`SCHEMA_VERSION` 是**归一后形状**的版本，不是输入数据的版本。形状变了就 +1，
两个下游都能据此判断是否需要重新 ingest。
"""

from __future__ import annotations

SCHEMA_VERSION = 1

__all__ = [
    "SCHEMA_VERSION",
    "jsonio",
    "loot",
    "recipe_ir",
    "recipe_slots",
    "recipes",
    "snbt",
    "trades",
]
