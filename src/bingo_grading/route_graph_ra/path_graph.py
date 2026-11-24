"""路线图的显示数据结构。

同构副本，来源：`ref/RecipeAnalysis/src/ra/report/paths/graph.py` 的
`PathGraph`（不含 `Builder`）。本仓库只复用它的**渲染契约**，图仍由
`adapter.to_path_graph()` 从本项目的 `PathTree` 构造。

与上游的同步约定同 `src/mcshared/`：字段增删要两边一起改，否则
`render.build_dot()` 会读到不存在的键。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PathGraph:
    """一张待渲染的图。只存显示需要的东西，不保留规则对象。"""

    nodes: dict[str, dict] = field(default_factory=dict)
    # (source, target, tag) -> (label, tooltip)
    edges: dict[tuple[str, str, str], tuple[str, str]] = field(default_factory=dict)
    edge_colors: dict[tuple[str, str, str], str] = field(default_factory=dict)
    dashed: set[tuple[str, str, str]] = field(default_factory=set)
    condition_edges: set[tuple[str, str, str]] = field(default_factory=set)
    omitted: dict[str, int] = field(default_factory=dict)
    blocked: dict[str, int] = field(default_factory=dict)
    rules: set[str] = field(default_factory=set)
    merged: set[str] = field(default_factory=set)
    groups: dict[str, int] = field(default_factory=dict)
    folded_tags: int = 0
    condition_leaves: int = 0
    folded_conditions: int = 0
    absorbed_assumptions: int = 0
    absorbed_roots: int = 0
    isomorphic: int = 0
    absorbed_members: int = 0
    buckets: int = 0
    isomorphic_clusters: int = 0
    collapsed_tables: int = 0
    pending_roots: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    suppressed: set[str] = field(default_factory=set)
    target: str = ""

    def edge_dropped(self, key: tuple[str, str, str]) -> None:
        """删一条边，同时清掉它在三个旁路集合里的登记。"""
        self.edges.pop(key, None)
        self.edge_colors.pop(key, None)
        self.dashed.discard(key)
        self.condition_edges.discard(key)
