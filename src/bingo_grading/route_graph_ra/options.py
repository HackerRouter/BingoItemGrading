"""路径图的呈现参数。

同构副本，来源：`ref/RecipeAnalysis/src/ra/report/paths/options.py`。
只保留渲染需要的参数；B1a 还没用到的折叠旋钮保持默认值。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

RANKDIRS = ("TB", "BT", "LR", "RL")


@dataclass(frozen=True)
class Param:
    name: str
    default: Any
    help: str
    metavar: str | None = None
    choices: tuple[str, ...] | None = None

    @property
    def flag(self) -> str:
        return f"--{self.name.replace('_', '-')}"


PARAMS: tuple[Param, ...] = (
    Param("depth", 4, "最大展开深度（每条边算一层）"),
    Param("branches", 4, "聚合组内最多展开几条具体规则；<=0 表示全部"),
    Param("max_nodes", 500, "节点总数上限"),
    Param("max_groups", 16, "一个节点最多画几个来源类别；<=0 表示不限"),
    Param("group_min", 3, "同一类来源达到几条才聚合成组节点；1 表示全部聚合"),
    Param("merge_isomorphic", 0, "同构配方簇折叠的最小成员数（0 = 关闭）", metavar="N"),
    Param("merge_leaves", 0, "叶子桶的条数门槛（0 = 关闭）", metavar="N"),
    Param("expand_tags", False, "展开 tag 的成员"),
    Param("expand_conditions", False, "展开条件（设备 / 工具 / 附魔）的上游"),
    Param("expand_groups", False, "展开聚合组内部的具体规则"),
    Param("keep_tables", False, "保留 table: 中转节点"),
    Param("keep_roots", False, "保留 world / assume 起点节点"),
    Param(
        "rankdir",
        "TB",
        "图的走向：TB 从上到下，BT 从下到上，LR 从左到右",
        choices=RANKDIRS,
    ),
)


def default_of(name: str) -> Any:
    return next(param.default for param in PARAMS if param.name == name)


@dataclass(frozen=True)
class PathOptions:
    depth: int = field(default=default_of("depth"))
    branches: int = field(default=default_of("branches"))
    max_nodes: int = field(default=default_of("max_nodes"))
    max_groups: int = field(default=default_of("max_groups"))
    group_min: int = field(default=default_of("group_min"))
    expand_tags: bool = field(default=default_of("expand_tags"))
    expand_conditions: bool = field(default=default_of("expand_conditions"))
    expand_groups: bool = field(default=default_of("expand_groups"))
    merge_isomorphic: int = field(default=default_of("merge_isomorphic"))
    merge_leaves: int = field(default=default_of("merge_leaves"))
    keep_tables: bool = field(default=default_of("keep_tables"))
    keep_roots: bool = field(default=default_of("keep_roots"))
    rankdir: str = field(default=default_of("rankdir"))

    def __post_init__(self) -> None:
        if self.rankdir not in RANKDIRS:
            raise ValueError(f"rankdir 必须是 {RANKDIRS} 之一，收到 {self.rankdir!r}")
        if self.depth < 1:
            raise ValueError(f"depth 至少为 1，收到 {self.depth}")
        if self.max_nodes < 2:
            raise ValueError(f"max_nodes 至少为 2，收到 {self.max_nodes}")
        if self.merge_isomorphic < 0 or self.merge_leaves < 0:
            raise ValueError("merge_isomorphic / merge_leaves 不能为负；0 表示关闭")
        if self.group_min < 1:
            raise ValueError(f"group_min 至少为 1，收到 {self.group_min}")

    def describe(self) -> list[str]:
        return [f"{param.flag} {getattr(self, param.name)}" for param in PARAMS]
