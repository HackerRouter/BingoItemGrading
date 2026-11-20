"""标签表：把上游 `facts/tag.jsonl` 读成「注册表 → 标签 → 成员」。

## 为什么要

两处都要它：

- 战利品表里的 `tag` 条目（如苦力怕掉唱片）要展开成物品，否则整条被跳过；
- 交易集的 `trades_ref: "#minecraft:armorer/level_1"` 指向 `minecraft:villager_trade`
  注册表里的标签，不展开就不知道某职业某等级卖什么。

## 形状

```json
{"payload": {"tag": "minecraft:armorer/level_1", "registry": "minecraft:villager_trade",
             "values": ["minecraft:armorer/1/..."], "nested": ["#minecraft:..."],
             "replace": false}}
```

`values` 里也可能出现 `#` 开头的嵌套引用，`nested` 是上游单独挑出来的那部分。
两者都收，展开时递归，带环检测。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

ITEM_REGISTRY = "minecraft:item"
TRADE_REGISTRY = "minecraft:villager_trade"

MAX_DEPTH = 8


class TagError(ValueError):
    """标签表不可用。"""


@dataclass
class TagSet:
    """`registry → tag id → 成员（含嵌套引用）`。"""

    by_registry: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)

    def members(self, tag: str, *, registry: str = ITEM_REGISTRY) -> tuple[str, ...]:
        """标签的成员，嵌套引用不展开。找不到时返回空元组。"""
        return self.by_registry.get(registry, {}).get(tag, ())

    def expand(self, tag: str, *, registry: str = ITEM_REGISTRY) -> tuple[str, ...]:
        """递归展开成最终成员，去重并保持首次出现顺序。"""
        out: list[str] = []
        seen_tags: set[str] = set()

        def walk(current: str, depth: int) -> None:
            if depth > MAX_DEPTH or current in seen_tags:
                return
            seen_tags.add(current)
            for value in self.members(current, registry=registry):
                name = value[1:] if value.startswith("#") else value
                if value.startswith("#"):
                    walk(name, depth + 1)
                elif name not in out:
                    out.append(name)

        walk(tag, 0)
        return tuple(out)

    def resolve_ref(self, ref: str, *, registry: str = ITEM_REGISTRY) -> tuple[str, ...]:
        """`#tag` 或普通 ID → 成员列表。非引用原样返回单元素元组。"""
        if ref.startswith("#"):
            return self.expand(ref[1:], registry=registry)
        return (ref,)

    def __len__(self) -> int:
        return sum(len(tags) for tags in self.by_registry.values())


def load(path: Path) -> TagSet:
    """读 `tag.jsonl`。文件不存在时返回空集合——调用方据此判断「没有标签数据」。"""
    path = Path(path)
    if not path.exists():
        return TagSet()
    out: TagSet = TagSet()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TagError(f"{path}: 不是合法 JSON：{exc}") from exc
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        tag = payload.get("tag")
        registry = payload.get("registry")
        if not isinstance(tag, str) or not isinstance(registry, str):
            continue
        values = [str(value) for value in (payload.get("values") or []) if isinstance(value, str)]
        nested = [str(value) for value in (payload.get("nested") or []) if isinstance(value, str)]
        merged = tuple(dict.fromkeys(values + [f"#{name.lstrip('#')}" for name in nested]))
        out.by_registry.setdefault(registry, {})[tag] = merged
    return out
