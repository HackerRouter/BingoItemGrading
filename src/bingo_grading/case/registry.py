"""目标注册表：物品 → 动作表构造函数。

**唯一入口。** CLI 的 `plan` 从这里取，不允许某个目标绕过引擎另写一条
计算路径——那正是这次重构要消掉的东西。

自 2026-11-12 起，目标不再需要登记也不需要写代码：`builder_for(任意物品)`
都会走 `bingo_grading.sources.actions.build()`，从上游来源索引（`build/<pack>/source_index.jsonl`，
3128 条 / 1414 个物品）自动拼动作图，再沿配方链递归补齐原料。

曾经的手写案例（`case/gold.py` / `case/redstone.py` / `case/portal.py`）已于
2026-11-17 删除；下界门的成本模型在 `sources/constructs.py` 的 `Construct` 表。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from bingo_grading.case.context import CaseContext
from bingo_grading.case.sources import ActionBundle
from bingo_grading.sources import actions as source_actions

Builder = Callable[[CaseContext], ActionBundle]


def auto_builder(
    item: str, *, pack: str | None = None, index_path: Path | None = None
) -> Builder:
    """从来源索引自动拼出 `item` 的动作图。任何物品都能用。"""

    def build(ctx: CaseContext) -> ActionBundle:
        built = source_actions.build(
            ctx, item, pack=pack, index_path=index_path
        )
        bundle = built.bundle
        # 未接入来源必须跟着动作表一起出去，否则调用方看不到遗漏。
        bundle.extras["uncovered"] = dict(built.uncovered.most_common())
        bundle.extras["uncovered_total"] = sum(built.uncovered.values())
        bundle.extras["source_records"] = built.records
        bundle.extras["source_by_type"] = dict(built.by_type)
        bundle.extras["gaps"] = built.gaps[:20]
        return bundle

    return build


_CACHE: dict[tuple[str, str | None, str | None], Builder] = {}


def builder_for(
    item: str, *, pack: str | None = None, index_path: Path | None = None
) -> Builder:
    """任何物品都有构造器——没有「未注册」这回事了。"""
    key = (item, pack, str(index_path) if index_path else None)
    found = _CACHE.get(key)
    if found is None:
        found = auto_builder(item, pack=pack, index_path=index_path)
        _CACHE[key] = found
    return found
