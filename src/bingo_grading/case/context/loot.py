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
        row = self._loot_row(subject, dimension, condition)
        if row is None:
            return None
        per_chest = row.value.get("per_trigger_expected") or {}
        return (
            {item: float(value) for item, value in per_chest.items()},
            f"{subject}[{row.condition}]",
        )

    def loot_cv(
        self,
        subject: str,
        item: str,
        *,
        dimension: str | None = None,
        condition: str = "tools=tools=present",
    ) -> float:
        """某结构/表**一次触发**产出该物品的相对标准差（`sd / mean`）。

        上游是 `stats/importers/loot.py` 写的 `per_trigger_cv`，源头是战利品表的
        `rolls` / 条目权重 / `set_count` 分布。没有数据时返回 0（按确定量处理），
        不猜——0 在 `Segment.cv` 里的含义正是「无方差信息」。
        """
        row = self._loot_row(subject, dimension, condition)
        if row is None:
            return 0.0
        spreads = row.value.get("per_trigger_cv") or {}
        value = spreads.get(item)
        return float(value) if isinstance(value, (int, float)) else 0.0

    def _loot_row(
        self,
        subject: str,
        dimension: str | None = None,
        condition: str = "tools=tools=present",
    ):
        """挑出适用的那一行 `loot_expectation`。

        维度只作为**偏好**，不是硬过滤：上游有些表把维度标错了
        （`chests/bastion_other` 标成 `minecraft:overworld`，它其实在下界），
        硬过滤会把整张表判成「没有数据」。表名本身已经唯一确定结构，
        按「同维度 → 空维度 → 其它维度」排序取第一条即可。
        """
        dimension = dimension or self.dimension
        condition = _normalize_condition(condition)
        candidates: list = [
            row
            for row in self.store.of("loot_expectation", subject)
            if _normalize_condition(row.condition) == condition
        ]
        candidates.sort(
            key=lambda row: 0 if row.dimension == dimension else (1 if not row.dimension else 2)
        )
        for row in candidates:
            if row.value.get("per_trigger_expected"):
                return row
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
