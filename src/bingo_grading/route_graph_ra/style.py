"""路径图的显示名与配色（裁剪版）。

同构副本，来源：`ref/RecipeAnalysis/src/ra/report/paths/style.py`。
只保留 `render.build_dot()` 实际用到的符号：`FILL` / `TARGET_*` /
`DEFAULT_EDGE_COLOR` / `short`。上游其余函数（`rule_label` 等）依赖
`ra.ir.Rule`，本仓库不引入那套规则模型。
"""

from __future__ import annotations

FILL = {
    "item": "#dbeafe",
    "block": "#dcfce7",
    "entity": "#fef9c3",
    "tag": "#f3e8ff",
    "table": "#ffe4e6",
    "station": "#e0e7ff",
    "tool": "#ffedd5",
    "enchant": "#fae8ff",
    "structure": "#ccfbf1",
    "world": "#99f6e4",
    "assume": "#e2e8f0",
    "flag": "#f1f5f9",
    "template": "#fde68a",
    "rule": "#f8fafc",
    "group": "#eef2ff",
    "bucket": "#e2e8f0",
    "omitted": "#fff7ed",
}

TARGET_FILL = "#fde68a"
TARGET_BORDER = "#b45309"
DEFAULT_EDGE_COLOR = "#94a3b8"


def short(value: str) -> str:
    """只为人读的短名；完整 id 留在 tooltip。"""
    return value.replace("minecraft:", "")
