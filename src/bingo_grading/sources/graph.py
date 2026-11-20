"""读取上游可达性项目的图产物 `graph.json`。

只读，不写上游目录。格式是字符串表 + 下标引用，规则行固定 8 列：

```
[id, head, body[], soft[], kind, family, meta(json), prov(json)]
```

`graph_schema` 不认识就报错，不尽力解析：一份被误解半截的图会产出一条
不存在的来源，比直接失败糟得多。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .constants import GRAPH_SCHEMA


class GraphError(Exception):
    """上游产物不可用（版本不符、缺字段、结构损坏）。"""


@dataclass(frozen=True)
class Rule:
    id: str
    head: str
    body: tuple[str, ...]
    soft: tuple[str, ...]
    kind: str
    family: str
    meta: dict

    @property
    def head_sort(self) -> str:
        return self.head.partition(":")[0]


@dataclass
class Graph:
    label: str
    ir_schema: int
    facts_digest: dict[str, int]
    rules: list[Rule] = field(default_factory=list)
    true_nodes: frozenset[str] = frozenset()
    unknown_nodes: dict[str, str] = field(default_factory=dict)
    _by_head: dict[str, list[Rule]] = field(default_factory=dict, repr=False)

    def index(self) -> None:
        self._by_head = {}
        for rule in self.rules:
            self._by_head.setdefault(rule.head, []).append(rule)

    def rules_for(self, head: str) -> list[Rule]:
        return self._by_head.get(head, [])

    def item_heads(self) -> list[str]:
        """所有 `item:` 为 head 的节点，按名字排序。"""
        return sorted(node for node in self._by_head if node.startswith("item:"))

    def is_true(self, node: str) -> bool:
        return node in self.true_nodes


def load(path: Path) -> Graph:
    path = Path(path)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GraphError(f"上游产物不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise GraphError(f"{path} 不是合法 JSON：{exc}") from exc

    if not isinstance(doc, dict):
        raise GraphError(f"{path} 顶层不是对象")

    version = doc.get("graph_schema")
    if version != GRAPH_SCHEMA:
        raise GraphError(
            f"{path} 的 graph_schema={version!r}，本程序只认 {GRAPH_SCHEMA}；"
            "重新跑上游的 `ra graph` 生成"
        )

    for key in ("strings", "rules", "states"):
        if key not in doc:
            raise GraphError(f"{path} 缺字段 {key!r}")

    strings = doc["strings"]
    if not isinstance(strings, list):
        raise GraphError(f"{path} 的 strings 不是数组")

    def text(index: object) -> str:
        if not isinstance(index, int) or isinstance(index, bool):
            raise GraphError(f"{path} 的字符串下标不是整数：{index!r}")
        if not 0 <= index < len(strings):
            raise GraphError(f"{path} 的字符串下标越界：{index}")
        return strings[index]

    rules: list[Rule] = []
    for seq, row in enumerate(doc["rules"]):
        if not isinstance(row, list) or len(row) != 8:
            raise GraphError(f"{path}: 第 {seq} 条规则行形状不对")
        try:
            meta = json.loads(text(row[6]))
            prov = json.loads(text(row[7]))
        except json.JSONDecodeError as exc:
            raise GraphError(f"{path}: 第 {seq} 条规则的 meta/prov 不是 JSON（{exc}）") from exc
        rules.append(
            Rule(
                id=text(row[0]),
                head=text(row[1]),
                body=tuple(text(index) for index in row[2]),
                soft=tuple(text(index) for index in row[3]),
                kind=text(row[4]),
                family=text(row[5]),
                meta=meta if isinstance(meta, dict) else {},
            )
        )
        # prov 在产物里是 `[input, file, ptr]` 三元组或 null。
        if prov is not None and not (isinstance(prov, list) and len(prov) == 3):
            raise GraphError(f"{path}: 第 {seq} 条规则的 prov 形状不对")

    states = doc["states"]
    if not isinstance(states, dict):
        raise GraphError(f"{path} 的 states 不是对象")
    true_nodes = states.get("true") or []
    unknown_nodes = states.get("unknown") or {}
    if not isinstance(true_nodes, list) or not isinstance(unknown_nodes, dict):
        raise GraphError(f"{path} 的 states 形状不对")

    graph = Graph(
        label=str(doc.get("label", "")),
        ir_schema=int(doc.get("ir_schema", 0)),
        facts_digest={str(k): int(v) for k, v in (doc.get("facts_digest") or {}).items()},
        rules=rules,
        true_nodes=frozenset(str(node) for node in true_nodes),
        unknown_nodes={str(k): str(v) for k, v in unknown_nodes.items()},
    )
    graph.index()
    return graph
