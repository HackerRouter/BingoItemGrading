"""统计改动 → 受影响节点的反向索引。

节点在计算前登记「我用了哪些查询」。统计改动后，`refresh()` 重新解析所有
登记过的查询，命中的行或行内容变了，就把对应节点标 dirty。只重算 dirty 子图。

不做「按主键前缀猜影响面」：回退链让一条粗层统计同时是很多细层查询的后备，
猜前缀会漏掉这些查询。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import WorldStatStore
from .resolver import Resolved, StatQuery, StatResolver

# 一次解析的指纹：命中的行 + 行内容。任一变化都意味着下游要重算。
Signature = tuple[tuple[str, ...] | None, str]


def _signature(resolved: Resolved) -> Signature:
    return (resolved.stat.key if resolved.stat else None, resolved.digest)


@dataclass
class DependencyIndex:
    """登记节点与查询的绑定关系。"""

    resolver: StatResolver
    _bindings: dict[str, list[StatQuery]] = field(default_factory=dict)
    _last: dict[tuple[str, ...], Signature] = field(default_factory=dict)
    _hits: dict[tuple[str, ...], tuple[str, ...] | None] = field(default_factory=dict)

    @classmethod
    def for_store(cls, store: WorldStatStore) -> DependencyIndex:
        return cls(resolver=StatResolver(store))

    def bind(self, owner_id: str, query: StatQuery) -> None:
        """登记一个节点用到的查询。同一对重复登记只算一次。"""
        queries = self._bindings.setdefault(owner_id, [])
        if query not in queries:
            queries.append(query)

    def bindings(self, owner_id: str) -> tuple[StatQuery, ...]:
        return tuple(self._bindings.get(owner_id, ()))

    def owners(self) -> list[str]:
        return sorted(self._bindings)

    def prime(self) -> None:
        """把当前解析结果记为基线，不产生 dirty。"""
        self.refresh()

    def refresh(self) -> set[str]:
        """重算全部登记查询，返回 dirty 的节点集合。"""
        dirty: set[str] = set()
        for owner_id, queries in self._bindings.items():
            for query in queries:
                resolved = self.resolver.resolve(query)
                signature = _signature(resolved)
                previous = self._last.get(query.key)
                self._last[query.key] = signature
                self._hits[query.key] = signature[0]
                if previous != signature:
                    dirty.add(owner_id)
        return dirty

    def owners_using(self, stat_key: tuple[str, ...]) -> set[str]:
        """当前命中该统计行的节点。用于诊断「改这行影响谁」。"""
        hit_queries = {key for key, hit in self._hits.items() if hit == stat_key}
        if not hit_queries:
            return set()
        return {
            owner_id
            for owner_id, queries in self._bindings.items()
            if any(query.key in hit_queries for query in queries)
        }

    def snapshot(self) -> dict:
        """诊断输出：每个节点的查询与命中行。"""
        return {
            owner_id: [
                {
                    "query": query.label(),
                    "stat_key": list(self._hits[query.key]) if self._hits.get(query.key) else None,
                }
                for query in queries
            ]
            for owner_id, queries in sorted(self._bindings.items())
        }
