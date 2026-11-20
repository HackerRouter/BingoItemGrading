"""直接来源 → 触发方式 → 战利品期望。

## 为什么要有这一层

来源索引以前用一张手工概率表（现在是 `gamedata.PROBABILITY_ROWS`）登记「这条来源有多大可能给物品」。
那份表只有 7 条，且是抄来的数字：橡树叶 5%、女巫红石 12.5%。这些数字本来就在
原版战利品表里（`random_chance` 条件、池的权重与 `set_count`），可以算，不必抄。

统计层把这些算好的数发布成 `loot_expectation` 行（`per_trigger_expected` +
`trigger`），这里只负责「按来源类别找到对应那一行」。

## 口径

`trigger` 是「触发一次」：方块破坏一次、生物击杀一次、箱子开一次、
剪毛/刷扫一次。产出按件计，所以 0.05 表示「平均每破坏 20 个方块得到 1 个」，
而不是「有 5% 概率得到 1 个」——两者在数量上等价，但前者可以直接乘次数。

## 为什么有两个条件

带工具与徒手的结果不同，而且**哪个更好取决于要拿什么**：橡树叶带剪刀只掉树叶，
徒手才掉木棍与树苗。所以同一 `(subject, trigger)` 有 `tools=present` 与
`tools=absent` 两行，查询时取对目标物品更有利的那一行，并把条件一起返回——
玩家可以选择用什么工具，模型不该替他假定。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..stats.model import WorldStat
from .constants import TRIGGER_BY_SOURCE

# 求值时同时考虑的两种工具条件。顺序不影响结果（取最大）。
CONDITIONS = ("tools=present", "tools=absent")


@dataclass
class DropIndex:
    """`(subject, trigger)` → `{物品: (期望件数, 成立条件)}`。"""

    table: dict[tuple[str, str], dict[str, tuple[float, str]]] = field(default_factory=dict)

    @classmethod
    def from_rows(
        cls,
        rows: list[WorldStat] | dict,
        *,
        conditions: tuple[str, ...] = CONDITIONS,
    ) -> "DropIndex":
        """从 `loot_expectation` 行建索引。同一物品多种条件时取期望大的那行。"""
        source = rows.values() if isinstance(rows, dict) else rows
        index = cls()
        for row in source:
            if row.stat_type != "loot_expectation":
                continue
            # 同一 subject 有多张表时，存储侧会在 condition 后补 `|trigger=kill`
            # 作为主键区分（否则击杀与剪毛会互相覆盖）。工具条件只是前半段。
            if row.condition.split("|", 1)[0] not in conditions:
                continue
            trigger = row.value.get("trigger")
            expected = row.value.get("per_trigger_expected")
            if not isinstance(trigger, str) or not isinstance(expected, dict):
                continue
            bucket = index.table.setdefault((row.subject, trigger), {})
            for item, amount in expected.items():
                if not isinstance(amount, (int, float)):
                    continue
                current = bucket.get(item)
                if current is None or float(amount) > current[0]:
                    bucket[item] = (float(amount), row.condition)
        return index

    def yield_for(self, item: str, source_type: str, subject: str) -> tuple[float, str] | None:
        """该来源触发一次给出物品的期望件数与对应条件；没有数据时返回 `None`。

        返回 `None` 与返回 `0.0` 含义不同：前者是「没测到」，后者是「测得掉零个」。
        """
        trigger = TRIGGER_BY_SOURCE.get(source_type)
        if trigger is None:
            return None
        expected = self.table.get((subject, trigger))
        if expected is None:
            return None
        return expected.get(item)

    def __len__(self) -> int:
        return len(self.table)
