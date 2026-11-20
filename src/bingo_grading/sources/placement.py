"""方块「在世界里哪生成」的事实索引。

## 为什么需要它

来源判定原来看战利品表路径（`blocks/redstone_wire`）就推断「这是地表方块」。
但表路径只说**破坏这个方块掉什么**，不说**这个方块在哪出现**。红石线的表在
`blocks/` 下，可这个方块只由古代城市模板放置，在 y≈-51。

两件事混在一起，结果是把「拆古代城市的红石线」记成「地表顺手捡」，
323 条来源受影响。

## 只认两类放置事实

上游 `block:` 节点的入边里，只有这两类说明「世界生成时它就存在」：

| 族 | 含义 | meta 里的凭据 |
|---|---|---|
| `worldgen` 且 `slot=block` | 由世界生成特性放置 | `source`（`feature/ore_gold_extra`） |
| `bindings/template_block` | 由结构模板放置 | `templates`（模板路径列表） |

其余入边都不是世界生成：

- `bridge/place`（`item:X` → `block:X`）是**玩家放置**，依赖已有物品，不是来源。
- `code/place_source` 同上。
- `code/transform` 是方块原地转换（铜氧化、斧剥皮），前提是方块已存在。
- `bridge/convention` 是玩家行为的结果（混凝土遇水固化）。

不认这几类，是为了避免「有红石就能放红石线，所以红石线是红石来源」这种循环。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .constants import TEMPLATE_FAMILY, WORLDGEN_FAMILY
from .graph import Graph


@dataclass(frozen=True)
class Placement:
    """一个方块的放置事实。两者可同时存在（如箱子既在特性里也在模板里）。"""

    block: str
    features: tuple[str, ...] = ()
    templates: tuple[str, ...] = ()

    @property
    def has_worldgen(self) -> bool:
        return bool(self.features)

    @property
    def structure_only(self) -> bool:
        """只由结构模板放置，没有任何世界生成特性。"""
        return bool(self.templates) and not self.features

    def as_dict(self) -> dict:
        return {
            "block": self.block,
            "features": list(self.features),
            "templates": list(self.templates),
        }


@dataclass
class PlacementIndex:
    """`block:` 节点 → 放置事实。"""

    blocks: dict[str, Placement] = field(default_factory=dict)

    @classmethod
    def from_graph(cls, graph: Graph) -> PlacementIndex:
        index = cls()
        features: dict[str, list[str]] = {}
        templates: dict[str, list[str]] = {}

        for rule in graph.rules:
            head = rule.head
            if not head.startswith("block:"):
                continue
            if rule.family == WORLDGEN_FAMILY and rule.meta.get("slot") == "block":
                source = rule.meta.get("source")
                if isinstance(source, str) and source:
                    bucket = features.setdefault(head, [])
                    if source not in bucket:
                        bucket.append(source)
            elif rule.family == TEMPLATE_FAMILY:
                raw = rule.meta.get("templates") or []
                bucket = templates.setdefault(head, [])
                for path in raw:
                    if isinstance(path, str) and path and path not in bucket:
                        bucket.append(path)

        for block in {*features, *templates}:
            index.blocks[block] = Placement(
                block=block,
                features=tuple(sorted(features.get(block, []))),
                templates=tuple(sorted(templates.get(block, []))),
            )
        return index

    def of(self, block: str) -> Placement | None:
        """`minecraft:redstone_wire` 或 `block:minecraft:redstone_wire` 都接受。"""
        key = block if block.startswith("block:") else f"block:{block}"
        return self.blocks.get(key)

    def structure_sets(self, block: str, maps) -> tuple[str, ...]:
        """该方块的模板所属结构集合。`maps` 是 `knowledge.StructureMaps`。"""
        placement = self.of(block)
        if placement is None or not placement.templates:
            return ()
        found: list[str] = []
        for path in placement.templates:
            set_id = maps.set_for_template(path)
            if set_id and set_id not in found:
                found.append(set_id)
        return tuple(sorted(found))

    def __len__(self) -> int:
        return len(self.blocks)
