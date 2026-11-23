"""`action_id` 前缀白名单：代码里出现的每一个前缀都必须在 `ACTION_PREFIXES` 里。

前缀被三处逻辑依赖（`grade.ATOMIC_PREFIXES` 的按件拆分判断、`Requirement.forbid`
的来源黑名单、`sources/actions/build.py` 的分类记账），拼错不会报错，只会让判断
静默失效。这个测试把「当天失败」提前。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from bingo_grading.plan.actions import ACTION_PREFIXES, Action, ActionError

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "bingo_grading"

# `action_id="loot:..."` / `action_id=f"loot:..."` 里冒号前的那一段。
LITERAL = re.compile(r'action_id=f?"([a-z_]+):')

# 前缀必须是裸标识符，不能带冒号（表里存的是冒号前那一半）。
PREFIX = re.compile(r"^[a-z_]+$")


def _literals() -> dict[str, set[str]]:
    """`{前缀: {出现在哪些文件}}`，只收字面量写法。"""
    found: dict[str, set[str]] = {}
    for path in SOURCE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in LITERAL.finditer(text):
            found.setdefault(match.group(1), set()).add(path.name)
    return found


def test_every_literal_prefix_is_registered() -> None:
    """代码里拼出来的前缀必须登记过。

    只扫字面量：`f"{node.action_prefix}:..."` 这类动态拼接查不到，但它背后
    的前缀（`gift` / `barter` / `fish` …）在 `_node_table` 里也是字面量，会被扫到。
    """
    unknown = {name: sorted(files) for name, files in _literals().items()
               if name not in ACTION_PREFIXES}
    assert not unknown, f"未登记的前缀（前缀 → 出现位置）：{unknown}"


def test_registry_entries_are_bare_identifiers() -> None:
    """表里存的是冒号前那一半，不能写成 `loot:`。"""
    bad = [name for name in ACTION_PREFIXES if not PREFIX.match(name)]
    assert not bad, f"前缀必须是裸标识符：{bad}"


def test_registry_has_no_duplicates() -> None:
    assert len(set(ACTION_PREFIXES)) == len(ACTION_PREFIXES)


def test_action_rejects_unregistered_prefix() -> None:
    """构造时就拦：动态拼出来的前缀（测试扫不到的那种）也会被挡住。"""
    with pytest.raises(ActionError):
        Action(
            action_id="loots:villages",  # 少了一个 o
            item="minecraft:coal",
            cost=1.0,
            yields={"minecraft:coal": 1.0},
        )


def test_dynamic_prefixes_are_registered() -> None:
    """`_node_table` 里那些 `action_prefix`（动态拼接，字面量扫描扫不到）也要在表里。"""
    from bingo_grading.sources.actions.common import NODE_TABLES

    missing = sorted(
        {node.action_prefix for node in NODE_TABLES} - set(ACTION_PREFIXES)
    )
    assert not missing, f"`NODE_TABLES` 用了未登记的前缀：{missing}"
