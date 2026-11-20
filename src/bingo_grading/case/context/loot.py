"""战利品期望：单箱、全条件、每次触发的产出。"""

from __future__ import annotations


from bingo_grading.sources.drops import TRIGGER_BY_SOURCE
from .model import Sourced, _normalize_condition

class LootMixin:
    # ---------------------------------------------------------------- 战利品

    def loot_per_chest(
        self,
        subject: str,
        item: str,
        *,
        dimension: str | None = None,
        condition: str = "tools=tools=present",
    ) -> Sourced | None:
        """某结构/表每箱给出该物品的期望数量。"""
        per_chest = self.loot_per_chest_all(
            subject, dimension=dimension, condition=condition
        )
        if per_chest is None or item not in per_chest[0]:
            return None
        return Sourced(
            float(per_chest[0][item]),
            "loot_expectation",
            per_chest[1],
        )


    def loot_per_chest_all(
        self,
        subject: str,
        *,
        dimension: str | None = None,
        condition: str = "tools=tools=present",
    ) -> tuple[dict[str, float], str] | None:
        """某结构/表的整份每箱期望。返回 `(物品 → 数量, 出处说明)`。

        需要把多种物品折算成同一目标时用它（金锭 = 金锭 + 金粒/9 + 金块×9）。
        """
        dimension = dimension or self.dimension
        condition = _normalize_condition(condition)
        # 维度只作为**偏好**，不是硬过滤：上游有些表把维度标错了
        # （`chests/bastion_other` 标成 `minecraft:overworld`，它其实在下界），
        # 硬过滤会把整张表判成「没有数据」。表名本身已经唯一确定结构，
        # 按「同维度 → 空维度 → 其它维度」排序取第一条即可。
        candidates: list = [
            row
            for row in self.store.of("loot_expectation", subject)
            if _normalize_condition(row.condition) == condition
        ]
        candidates.sort(
            key=lambda row: 0 if row.dimension == dimension else (1 if not row.dimension else 2)
        )
        for row in candidates:
            per_chest = row.value.get("per_trigger_expected") or {}
            if not per_chest:
                continue
            return (
                {item: float(value) for item, value in per_chest.items()},
                f"{subject}[{row.condition}]",
            )
        return None


    def yield_per_trigger(
        self,
        *,
        source_type: str,
        subject: str,
        item: str,
        condition: str = "",
    ) -> Sourced | None:
        """某直接来源「触发一次」给出该物品的期望件数。

        口径统一：方块 = 破坏一次、生物 = 击杀一次、箱子 = 开一次、
        剪毛/刷扫同方块。数量取自战利品表的期望求值，不来自手工概率表。

        `condition` 留空时在「带工具」与「徒手」两种条件里取对目标物品更有利的
        那个——用什么工具是玩家的选择，模型不该替他假定。
        """
        trigger = TRIGGER_BY_SOURCE.get(source_type)
        if trigger is None:
            return None
        condition = _normalize_condition(condition)
        best: Sourced | None = None
        for row in self.store.of("loot_expectation", subject):
            if row.value.get("trigger") != trigger:
                continue
            if condition and _normalize_condition(row.condition) != condition:
                continue
            expected = row.value.get("per_trigger_expected") or {}
            if item not in expected:
                continue
            value = float(expected[item])
            if best is None or value > best.value:
                best = Sourced(
                    value,
                    "loot_expectation",
                    f"{subject}/{trigger}[{row.condition}]",
                )
        return best
