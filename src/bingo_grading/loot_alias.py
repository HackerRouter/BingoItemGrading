"""`dropsLike` 别名：挂墙变体共用本体的战利品表。

MC 里 `minecraft:wall_torch` 没有自己的 loot table —— 方块属性写了
`dropsLike(TORCH)`，运行时直接读 `blocks/torch`。上游把这条关系导出成
`code_link.jsonl` 的 `idiom == "loot_alias"`，26.3 共 47 条：

| 类别 | 条数 |
|---|---:|
| `*_wall_sign` ← `*_sign` | 13 |
| `*_wall_hanging_sign` ← `*_hanging_sign` | 14 |
| `*_coral_wall_fan` ← `*_coral_fan` | 10 |
| `*_wall_torch` ← `torch` | 4 |
| `*_wall_head` / `*_wall_skull` | 7 |

**为什么需要它**：`structure_content.blocks_per_start` 的键是**方块名**（结构里
放的是 `wall_torch`），而 `loot_expectation` 的 subject 由**表名**派生（只有
`minecraft:torch` 一行）。不把这层别名铺开，就会出现「结构里明明有一排火把，
模型却说这个方块没有结构来源」。产出端是通的（共表），缺的只是输入端。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from . import paths

# 记录里方块名前缀。
_BLOCK = "block:"


@lru_cache(maxsize=4)
def _read(path: str) -> dict[str, tuple[str, ...]]:
    """解析 `code_link.jsonl`。读不到、或某行坏掉都只跳过，不抛。"""
    file = Path(path)
    if not file.exists():
        return {}
    out: dict[str, list[str]] = {}
    for line in file.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            continue
        payload = raw.get("payload") or {}
        if payload.get("idiom") != "loot_alias":
            continue
        link = payload.get("link") or {}
        meta = payload.get("meta") or {}
        base = str(meta.get("alias_of") or "")
        if not base.startswith(_BLOCK):
            continue
        base = base[len(_BLOCK):]
        for variant in link.get("via") or ():
            name = str(variant)
            if not name.startswith(_BLOCK):
                continue
            name = name[len(_BLOCK):]
            if name and name != base:
                out.setdefault(base, []).append(name)
    return {key: tuple(dict.fromkeys(value)) for key, value in out.items()}


def load(pack: str | None = None) -> dict[str, tuple[str, ...]]:
    """`{本体方块: (挂墙变体, ...)}`。

    数据缺失时返回空字典：调用方还有按命名约定拼的兜底（见
    `case.context.model._with_wall_variants`），不能因为上游没同步就让建图失败。
    """
    if not pack:
        return {}
    resolved = paths.recipe_analysis(pack)
    if not resolved.exists:
        return {}
    return _read(str(resolved.path / "facts" / "code_link.jsonl"))
