"""上游前置的闭包展开。

上游规则 `head ← body` 的 body 里既有叶子前提（`world:` / `tool:` / …），
也有中间节点（`table:` / `block:` / `entity:`）。本模块把中间节点递归展开，
只留下可归类的叶子。

展开与保留的边界：

| 前缀 | 处理 |
|---|---|
| `world` `structure` `tool` `station` `assume` `enchant` | 叶子，收集 |
| `table` `block` `entity` | 展开 |
| `item` `tag` `flag` | 不展开，进注记 |

`item` 不展开：它是链式前置（要绿宝石），属于策略，不是「顺手能到」的世界条件。
展开它会把合成树整棵拉进来，既爆量又与合成展开器重复计代价。
"""

from __future__ import annotations

from dataclasses import dataclass

from .constants import BIOME_SOURCE_PREFIX, EXPAND_PREFIXES, LEAF_PREFIXES
from .graph import Graph

# 单条来源的闭包上限。超过即截断并标记，不静默继续。
MAX_NODES = 256
MAX_DEPTH = 12


@dataclass(frozen=True)
class Closure:
    """一次闭包展开的结果。`truncated` 为真表示撞到上限，结果不完整。"""

    prereq: tuple[str, ...]
    notes: tuple[str, ...]
    biomes: tuple[str, ...]
    cycles: tuple[str, ...]
    truncated: bool


class _Collector:
    def __init__(self) -> None:
        self.prereq: list[str] = []
        self.notes: list[str] = []
        self.biomes: list[str] = []
        self.cycles: list[str] = []
        self._prereq_seen: set[str] = set()
        self._note_seen: set[str] = set()
        self._biome_seen: set[str] = set()
        self._cycle_seen: set[str] = set()
        self.seen: set[str] = set()
        self.truncated = False

    def leaf(self, node: str) -> None:
        if node not in self._prereq_seen:
            self._prereq_seen.add(node)
            self.prereq.append(node)

    def note(self, node: str) -> None:
        if node not in self._note_seen and node not in self._prereq_seen:
            self._note_seen.add(node)
            self.notes.append(node)

    def biome(self, name: str) -> None:
        if name not in self._biome_seen:
            self._biome_seen.add(name)
            self.biomes.append(name)

    def cycle(self, node: str) -> None:
        if node not in self._cycle_seen:
            self._cycle_seen.add(node)
            self.cycles.append(node)


def expand(graph: Graph, nodes: tuple[str, ...]) -> Closure:
    """展开一组前置节点。结果保序、去重。"""
    collector = _Collector()

    def visit(node: str, depth: int, path: frozenset[str]) -> None:
        prefix = node.partition(":")[0]
        if prefix in LEAF_PREFIXES:
            collector.leaf(node)
            return
        if prefix not in EXPAND_PREFIXES:
            collector.note(node)
            return
        if node in path:
            collector.cycle(node)
            return
        if node in collector.seen:
            return
        if depth >= MAX_DEPTH or len(collector.seen) >= MAX_NODES:
            collector.truncated = True
            collector.note(node)
            return

        rules = graph.rules_for(node)
        if not rules:
            # 上游没有任何规则产出它：状态为真说明是播种节点，保留为注记。
            collector.note(node)
            return

        collector.seen.add(node)
        for rule in rules:
            source = rule.meta.get("source")
            if isinstance(source, str) and source.startswith(BIOME_SOURCE_PREFIX):
                collector.biome(source[len(BIOME_SOURCE_PREFIX) :])
            for child in rule.body:
                visit(child, depth + 1, path | {node})

    for node in nodes:
        visit(node, 0, frozenset())

    return Closure(
        prereq=tuple(collector.prereq),
        notes=tuple(collector.notes),
        biomes=tuple(collector.biomes),
        cycles=tuple(collector.cycles),
        truncated=collector.truncated,
    )
