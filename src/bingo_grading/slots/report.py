"""槽位覆盖率报告。

报告回答三个问题：哪些「路线 × 获取方式」格子有自动候选、哪些是空的；
空格子是因为设计上不产生自动候选，还是因为枚举漏了；合成展开有没有
撞到深度上限或环。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ..sources.index import SourceRecord
from .build import METHODS, ROUTES, Slot, SlotBuild

# 按约定不产生自动候选的格子与原因。
DESIGN_EMPTY = {
    "branch_mine": "仅策略注册可覆盖：鱼骨挖掘是玩家拿到工具后的主动策略",
    "farm": "需由「作物方块可达 + 种子来源可达」推导，来源条目没有这一类",
}


@dataclass(frozen=True)
class Cell:
    route: str
    obtain_method: str
    items: int

    def as_dict(self) -> dict:
        return {"route": self.route, "obtain_method": self.obtain_method, "items": self.items}


def report(build: SlotBuild, records: list[SourceRecord]) -> dict:
    slots = build.slots
    counts = Counter((slot.route, slot.obtain_method) for slot in slots)
    items = {slot.item for slot in slots}
    source_items = {record.item for record in records}

    cells = [
        Cell(route=route, obtain_method=method, items=counts[(route, method)])
        for route in ROUTES
        for method in METHODS
        if counts[(route, method)]
    ]

    empty_cells = []
    for route in ROUTES:
        for method in METHODS:
            if counts[(route, method)]:
                continue
            reason = DESIGN_EMPTY.get(route) or DESIGN_EMPTY.get(method)
            empty_cells.append(
                {
                    "route": route,
                    "obtain_method": method,
                    "by_design": reason is not None,
                    "reason": reason or "枚举盲区：该格子无任何物品的自动候选",
                }
            )

    routes_per_item: dict[str, set[str]] = {}
    for slot in slots:
        routes_per_item.setdefault(slot.item, set()).add(slot.route)

    single_route = sorted(
        item for item, routes in routes_per_item.items() if len(routes) == 1
    )

    direct = sum(1 for slot in slots if slot.min_craft_depth == 0)
    crafted = len(slots) - direct

    return {
        "items": len(items),
        "slots": len(slots),
        "sources": len(records),
        "direct_slots": direct,
        "craft_slots": crafted,
        "cells": [cell.as_dict() for cell in cells],
        "empty_cells": empty_cells,
        "items_without_slots": sorted(source_items - items),
        "unexpanded_items": build.unexpanded[:20],
        "unexpanded_count": len(build.unexpanded),
        "single_route_count": len(single_route),
        "single_route_examples": single_route[:20],
        "craft": build.stats.as_dict(),
    }


def item_slots(slots: list[Slot], item: str) -> list[Slot]:
    """单物品的槽位清单，按路线与方式排序。"""
    return sorted(
        (slot for slot in slots if slot.item == item),
        key=lambda slot: (ROUTES.index(slot.route), METHODS.index(slot.obtain_method)),
    )
