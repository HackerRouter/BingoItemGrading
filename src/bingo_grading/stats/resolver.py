"""查询解析：按 `biome_subject → biome → dimension → global` 回退。

回退只降 `scope_level`，`subject` 与 `condition` 全程不变。
命中即返回，并记录回退了几层与该行的 `confidence`。

完全缺失时不编默认数值：返回值是 `None`，`confidence` 记为 `none`。
编一组 0 会让下游算出「代价为零」的免费物品，而这是静默坏数据。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .model import FACT_TYPES, SCOPE_ORDER, SPATIAL_TYPES, StatError, WorldStat, WorldStatStore


@dataclass(frozen=True)
class StatQuery:
    """一次统计查询。空串表示该维度不参与。"""

    pack_version: str
    stat_type: str
    dimension: str = ""
    biome: str = ""
    subject: str = ""
    condition: str = ""

    @property
    def key(self) -> tuple[str, ...]:
        return (
            self.pack_version,
            self.stat_type,
            self.dimension,
            self.biome,
            self.subject,
            self.condition,
        )

    def scope_start(self) -> int:
        """最细可用的 `scope_level` 在 `SCOPE_ORDER` 中的下标。"""
        if self.biome and self.subject:
            return 0
        if self.biome:
            return 1
        if self.dimension:
            return 2
        return 3

    def label(self) -> str:
        parts = [self.stat_type, self.dimension or "*", self.biome or "*", self.subject or "*"]
        if self.condition:
            parts.append(self.condition)
        return "|".join(parts)


@dataclass(frozen=True)
class Resolved:
    """一次查询的结果。

    `fallback_level` 是**命中层的绝对层号**（`SCOPE_ORDER` 下标）：
    0 = `biome_subject`，1 = `biome`，2 = `dimension`，3 = `global`。
    不用「候选序号」：同一层命中会因查询带不带 `subject` 而给出不同数值，
    `ore_density`（只有群系层）与 `biome_patch`（天然无 subject）就会对不上。
    完全缺失时为 `None`。
    """

    query: StatQuery
    stat: WorldStat | None
    scope_level: str | None
    fallback_level: int | None
    confidence: str

    @property
    def value(self) -> dict | None:
        return self.stat.value if self.stat else None

    @property
    def missing(self) -> bool:
        return self.stat is None

    @property
    def digest(self) -> str:
        """命中行的内容指纹。用于判断「同一行被改了值」也算变化。"""
        if self.stat is None:
            return "none"
        payload = {
            "value": self.stat.value,
            "sample_size": self.stat.sample_size,
            "confidence": self.stat.confidence,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def as_dict(self) -> dict:
        """诊断输出用。`fallback_level` 为 None 时写 `none`。"""
        return {
            "query": self.query.label(),
            "scope_level": self.scope_level,
            "fallback_level": "none" if self.fallback_level is None else self.fallback_level,
            "confidence": self.confidence,
            "stat_key": list(self.stat.key) if self.stat else None,
            "value": self.value,
        }


def _candidate_keys(query: StatQuery, start: int) -> list[tuple[str, ...]]:
    """从最细层往下构造候选主键。不适用层直接跳过。"""
    keys: list[tuple[str, ...]] = []
    for index in range(start, len(SCOPE_ORDER)):
        scope = SCOPE_ORDER[index]
        if scope == "biome" and not query.biome:
            continue
        if scope == "dimension" and not query.dimension:
            continue
        if scope == "global":
            keys.append(
                (query.pack_version, "global", "", "", query.stat_type, query.subject, query.condition)
            )
            continue
        biome = query.biome if scope in ("biome", "biome_subject") else ""
        keys.append(
            (query.pack_version, scope, query.dimension, biome, query.stat_type, query.subject, query.condition)
        )
    return keys


class StatResolver:
    """带缓存的解析器。

    缓存以 `store.revision` 为版本：统计一改，revision 变化，缓存整体作废。
    同一查询在一次全量计算里只查一次。
    """

    def __init__(self, store: WorldStatStore, *, cache: bool = True) -> None:
        self._store = store
        self._cache_enabled = cache
        self._revision = store.revision
        self._cache: dict[tuple[str, ...], Resolved] = {}
        self.hits: dict[str, int] = {}

    def _sync(self) -> None:
        if self._revision != self._store.revision:
            self._cache.clear()
            self._revision = self._store.revision

    def resolve(self, query: StatQuery) -> Resolved:
        if query.stat_type not in SPATIAL_TYPES:
            hint = (
                "命名事实按 (stat_type, subject, condition) 精确连接，没有层级回退；用 store.of(...) 取"
                if query.stat_type in FACT_TYPES
                else "未知 stat_type"
            )
            raise StatError(f"{query.stat_type}：{hint}")
        self._sync()
        if self._cache_enabled:
            cached = self._cache.get(query.key)
            if cached is not None:
                self.hits[query.stat_type] = self.hits.get(query.stat_type, 0) + 1
                return cached

        start = query.scope_start()
        resolved: Resolved | None = None
        for key in _candidate_keys(query, start):
            stat = self._store.rows.get(key)
            if stat is None:
                continue
            resolved = Resolved(
                query=query,
                stat=stat,
                scope_level=stat.scope_level,
                fallback_level=SCOPE_ORDER.index(stat.scope_level),
                confidence=stat.confidence,
            )
            break
        if resolved is None:
            resolved = Resolved(
                query=query,
                stat=None,
                scope_level=None,
                fallback_level=None,
                confidence="none",
            )

        if self._cache_enabled:
            self._cache[query.key] = resolved
        return resolved

    def resolve_all(self, queries: list[StatQuery]) -> list[Resolved]:
        return [self.resolve(query) for query in queries]


def require_value(resolved: Resolved, *, consumer: str) -> dict:
    """取 `value`；缺失时抛错，让调用方显式处理而不是拿到空值继续算。"""
    if resolved.value is None:
        raise StatError(
            f"{consumer} 需要的统计缺失：{resolved.query.label()}（pack={resolved.query.pack_version}）"
        )
    return resolved.value
