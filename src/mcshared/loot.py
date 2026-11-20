"""战利品表的语法归一：两套方言 → 一个形状。

## 两套方言

| 位置 | modern（26.x） | legacy（≤1.20） |
|---|---|---|
| 函数数组 | `modifier`（对象或数组） | `functions` |
| 条件 | 单数 `condition`，可写字符串引用 predicate | 数组 `conditions` |
| 条件内类型键 | `type` | `condition` |
| 序列 | `random_sequence` 存在 | 无 |

方言按**每个文件自身**的形状判定，不依赖全局主方言：数据包可以混用，
少数样本必须各自解析。判据是 `random_sequence` 是否存在，这是数据驱动出来的
（26.x datagen 必写，旧版不写），不是按版本号猜。

## 产出

`normalize_table(doc, table_id)` → `Table`。`Table.pools[i].entries[j]` 是树，
不是摊平的列表——期望计算要按 `alternatives` 的分支顺序求概率，摊平会丢结构。

`flatten_entry()` / `fact_payload()` 给需要**逐条目一行**的消费者
（RecipeAnalysis 的 facts 就是这种形状）。摊平会丢掉「二选一」与「两个都给」的区别，
所以每个条目带 `weight` / `quality`（原数据写了才出）与 `group_id` / `group_kind`。

## 不做事的部分

未登记的函数/条件类型不静默丢弃：记进 `missing`，由调用方决定怎么处理。
这里不做类型解释，`set_count` 怎么算期望不归本模块管。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

SCHEMA_VERSION = 1

# 数据包里出现过的条目类型。未登记的新类型进 `missing`，不猜。
ENTRY_KINDS = frozenset(
    {
        "empty",
        "item",
        "loot_table",
        "dynamic",
        "tag",
        "slots",
        "alternatives",
        "sequence",
        "group",
    }
)

# 会带子条目的类型。子条目的选中语义各不相同，这里只负责「有子节点」。
CONTAINER_KINDS = frozenset({"alternatives", "sequence", "group"})

# 能改写产物身份的复合函数：原料之外还要保留其参数。
IDENTITY_KEYS = frozenset(
    {
        "set_components",
        "set_potion",
        "set_random_potion",
        "set_enchantments",
        "enchant_randomly",
        "enchant_with_levels",
        "copy_components",
        "set_contents",
        "set_loot_table",
        "set_stew_effect",
        "set_banner_pattern",
        "set_instrument",
        "set_fireworks",
        "exploration_map",
        "furnace_smelt",
        "set_count",
    }
)

# `extra` 要排掉的键：这些已被结构化的字段吸收，留在 extra 里是重复。
EXCLUDED_ENTRY_KEYS = frozenset(
    {
        "type",
        "name",
        "children",
        "conditions",
        "condition",
        "functions",
        "modifier",
        "weight",
        "quality",
    }
)

MAX_DEPTH = 8


def local_id(ident: str) -> str:
    """`minecraft:item` → `item`。"""
    return ident.split(":", 1)[-1]


def condition_type(node: object) -> str | None:
    """取条件类型。modern 对象用 `type`，legacy 对象用 `condition`；字符串指向 predicate。"""
    if isinstance(node, str):
        return f"predicate:{local_id(node)}"
    if isinstance(node, dict):
        for key in ("type", "condition"):
            value = node.get(key)
            if isinstance(value, str):
                return local_id(value)
    return None


def _one_condition(node: object, missing: list[str]) -> list[dict]:
    kind = condition_type(node)
    if kind is None:
        missing.append(f"条件无法识别类型：{type(node).__name__}")
        return []
    if isinstance(node, str):
        return [{"type": kind, "ref": node}]
    body = {key: value for key, value in node.items() if key not in ("type", "condition")}
    return [{"type": kind, **body}]


def normalize_conditions(node: dict) -> tuple[list[dict], list[str]]:
    """把一个容器（表/池/条目）上的条件归一成列表。"""
    out: list[dict] = []
    missing: list[str] = []

    single = node.get("condition")
    if single is not None:
        out.extend(_one_condition(single, missing))

    many = node.get("conditions")
    if many is not None:
        if isinstance(many, list):
            for item in many:
                out.extend(_one_condition(item, missing))
        else:
            missing.append("conditions 不是数组")

    return out, missing


def normalize_functions(node: dict) -> tuple[list[dict], list[str]]:
    """把 `modifier` / `functions` 归一成 `{"function": <局部名>, ...参数}` 列表。"""
    out: list[dict] = []
    missing: list[str] = []

    for key in ("modifier", "functions"):
        raw = node.get(key)
        if raw is None:
            continue
        nodes = raw if isinstance(raw, list) else [raw]
        for item in nodes:
            if not isinstance(item, dict):
                missing.append(f"{key} 含非对象项")
                continue
            ident = item.get("function") or item.get("type")
            if not isinstance(ident, str):
                missing.append(f"{key} 项缺少 function/type")
                continue
            body = {k: v for k, v in item.items() if k not in ("function", "type")}
            out.append({"function": local_id(ident), **body})
    return out, missing


@dataclass(frozen=True)
class Entry:
    """条目树的一个节点。`raw` 保留原始对象，供还需要未归一字段的消费者使用。"""

    kind: str
    name: str | None
    weight: float
    quality: float | None
    conditions: tuple[dict, ...]
    functions: tuple[dict, ...]
    children: tuple["Entry", ...]
    raw: dict
    missing: tuple[str, ...] = ()

    @property
    def is_container(self) -> bool:
        return self.kind in CONTAINER_KINDS

    @property
    def nested_table(self) -> str | None:
        """嵌套表条目的表 ID：26.3 放在 `value`，旧版放在 `name`。"""
        if self.kind != "loot_table":
            return None
        if self.name is not None:
            return self.name
        value = self.raw.get("value")
        return value if isinstance(value, str) else None

    @property
    def inline_table(self) -> dict | None:
        """内联嵌套表：`value` 直接写成表对象（`equipment/*` 就是这种）。

        这类条目没有表 ID，只能就地求值。旧实现把它当成「未处理类型」丢掉了。
        """
        if self.kind != "loot_table":
            return None
        value = self.raw.get("value")
        return value if isinstance(value, dict) else None

    @property
    def tag_ref(self) -> str | None:
        """`tag` 条目指向的标签 ID。

        26.x 写在 `items`（可带 `#` 前缀，如 `#minecraft:creeper_drop_music_discs`），
        旧写法把裸名放在 `name`。
        """
        if self.kind != "tag":
            return None
        raw = self.raw.get("items")
        if isinstance(raw, str):
            return raw.lstrip("#")
        return self.name

    @property
    def extra(self) -> dict:
        return {key: value for key, value in self.raw.items() if key not in EXCLUDED_ENTRY_KEYS}

    @property
    def declared_children(self) -> int:
        """原始 `children` 的条目数；不是数组时为 0（与事实形状保持一致）。"""
        raw = self.raw.get("children")
        return len(raw) if isinstance(raw, list) else 0


def _entry(node: object, depth: int) -> tuple[Entry | None, list[str]]:
    if depth > MAX_DEPTH:
        return None, ["条目嵌套过深"]
    if not isinstance(node, dict):
        return None, [f"条目不是对象：{type(node).__name__}"]

    ident = node.get("type")
    if not isinstance(ident, str):
        return None, ["条目缺少 type"]
    kind = local_id(ident)

    missing: list[str] = []
    if kind not in ENTRY_KINDS:
        missing.append(f"未登记的条目类型 {kind}")

    conditions, cond_missing = normalize_conditions(node)
    missing.extend(cond_missing)
    functions, fn_missing = normalize_functions(node)
    missing.extend(fn_missing)

    children: list[Entry] = []
    raw_children = node.get("children")
    if isinstance(raw_children, list):
        for child in raw_children:
            one, child_missing = _entry(child, depth + 1)
            if one is not None:
                children.append(one)
            missing.extend(child_missing)

    weight = node.get("weight")
    quality = node.get("quality")

    return (
        Entry(
            kind=kind,
            name=node.get("name") if isinstance(node.get("name"), str) else None,
            weight=float(weight) if isinstance(weight, (int, float)) else 1.0,
            quality=float(quality) if isinstance(quality, (int, float)) else None,
            conditions=tuple(conditions),
            functions=tuple(functions),
            children=tuple(children),
            raw=node,
            missing=tuple(missing),
        ),
        list(missing),
    )


@dataclass(frozen=True)
class Pool:
    rolls: Any
    bonus_rolls: Any
    conditions: tuple[dict, ...]
    functions: tuple[dict, ...]
    entries: tuple[Entry, ...]
    raw: dict

    @property
    def weight_total(self) -> float:
        return sum(entry.weight for entry in self.entries)


@dataclass(frozen=True)
class Table:
    id: str
    kind: str | None
    dialect: str
    random_sequence: Any
    pools: tuple[Pool, ...]
    raw: dict
    missing: tuple[str, ...] = ()


def _pool(node: object, index: int) -> tuple[Pool | None, list[str]]:
    if not isinstance(node, dict):
        return None, [f"pool[{index}] 不是对象"]

    missing: list[str] = []
    conditions, cond_missing = normalize_conditions(node)
    missing.extend(f"{index}: {m}" for m in cond_missing)

    entries: list[Entry] = []
    raw_entries = node.get("entries")
    if isinstance(raw_entries, list):
        for entry in raw_entries:
            one, entry_missing = _entry(entry, 0)
            if one is not None:
                entries.append(one)
            missing.extend(f"{index}: {m}" for m in entry_missing)
    elif raw_entries is not None:
        missing.append(f"pool[{index}].entries 不是数组")

    functions, fn_missing = normalize_functions(node)
    missing.extend(f"{index}: {m}" for m in fn_missing)

    return (
        Pool(
            rolls=node.get("rolls", 1),
            bonus_rolls=node.get("bonus_rolls"),
            conditions=tuple(conditions),
            functions=tuple(functions),
            entries=tuple(entries),
            raw=node,
        ),
        missing,
    )


def normalize_table(doc: dict, table_id: str) -> Table:
    """把一份战利品表 JSON 归一成 `Table`。

    `doc` 的顶层必须是对象；不是对象由调用方在读取阶段就挡掉。
    """
    if not isinstance(doc, dict):
        raise TypeError(f"战利品表顶层不是对象：{table_id}")

    missing: list[str] = []
    kind = doc.get("type")
    kind = local_id(kind) if isinstance(kind, str) else None

    dialect = "modern" if "random_sequence" in doc else "legacy"

    pools: list[Pool] = []
    raw_pools = doc.get("pools")
    if raw_pools is None:
        pools = []
    elif not isinstance(raw_pools, list):
        missing.append("pools 不是数组")
    else:
        for index, node in enumerate(raw_pools):
            one, pool_missing = _pool(node, index)
            if one is not None:
                pools.append(one)
            missing.extend(pool_missing)

    if not pools and kind is None:
        missing.append("既无 pools 也无 type")
    # 触发型空表（可疑方块、雕刻南瓜）是合法输入：只有 type 没有 pools，不算缺项。

    sequence = doc.get("random_sequence")
    return Table(
        id=table_id,
        kind=kind,
        dialect=dialect,
        random_sequence=sequence,
        pools=tuple(pools),
        raw=doc,
        missing=tuple(missing),
    )


def walk(entries: tuple[Entry, ...]) -> Iterator[Entry]:
    """前序遍历，父节点在子节点之前。"""
    for entry in entries:
        yield entry
        yield from walk(entry.children)


def walk_entry(node: object, depth: int = 0) -> tuple[list[dict], list[str]]:
    """单个条目树 → 摊平的事实行（父在前，深度优先）。

    需要树形结构的消费者用 `_entry()` / `Table`；这个函数是给「一行一个条目」
    的事实形状用的。分组 id 以 `e0` 为根，与 `flatten_pool` 的 `p<i>e<j>` 同一套写法。
    """
    entry, missing = _entry(node, depth)
    if entry is None:
        return [], missing
    rows: list[dict] = []
    _flatten_tree(entry, "e0", None, None, rows)
    return rows, missing


def flatten_entry(entry: Entry) -> dict:
    """一个条目 → 一行事实。键序固定，产物可比对。

    `weight` / `quality` 只在原数据写了才出：缺省与显式 1 是不同的事实
    （前者「没参与权重竞争」，后者「参与且权重 1」），下游按 `weight ?? 1` 读。
    """
    row: dict[str, Any] = {
        "kind": entry.kind,
        "name": entry.name,
    }
    if "weight" in entry.raw:
        row["weight"] = _number(entry.weight)
    if entry.quality is not None:
        row["quality"] = _number(entry.quality)
    row["children"] = entry.declared_children
    row["conditions"] = [dict(condition) for condition in entry.conditions]
    row["functions"] = [dict(function) for function in entry.functions]
    row["extra"] = entry.extra
    return row


def _number(value: float) -> int | float:
    """整数权重输出成整数：`20.0` 与 `20` 在下游是同一个值，但前者读起来像浮点统计量。"""
    return int(value) if float(value).is_integer() else value


def _flatten_tree(
    entry: Entry,
    path: str,
    group_id: str | None,
    group_kind: str | None,
    out: list[dict],
) -> None:
    """条目树 → 摊平的事实行（父在前，深度优先）。

    子条目按原顺序摊到同层，带 `group_id`（所在分组）与 `group_kind`
    （`alternatives` / `group` / `sequence`）：只留 `children` 计数的话，
    「二选一」与「两个都给」在事实层面长得一模一样。
    容器自身的行同时带自己的 id 与类型，子条目的 `group_id` 能对上它。
    """
    row = flatten_entry(entry)
    if entry.is_container:
        row["group_id"] = path
        row["group_kind"] = entry.kind
    elif group_id is not None:
        row["group_id"] = group_id
        row["group_kind"] = group_kind
    out.append(row)
    for index, child in enumerate(entry.children):
        _flatten_tree(child, f"{path}c{index}", path, entry.kind, out)


def flatten_pool(pool: Pool, index: int = 0) -> dict:
    entries: list[dict] = []
    for position, entry in enumerate(pool.entries):
        _flatten_tree(entry, f"p{index}e{position}", None, None, entries)
    return {
        "rolls": pool.rolls,
        "bonus_rolls": pool.bonus_rolls,
        "conditions": [dict(condition) for condition in pool.conditions],
        "entries": entries,
        "functions": [dict(function) for function in pool.functions],
    }


def fact_payload(table: Table) -> dict:
    """归一的表 → RecipeAnalysis 的事实 payload（键序与历史产物一致）。"""
    return {
        "type": table.kind,
        "dialect": table.dialect,
        "pools": [flatten_pool(pool, index) for index, pool in enumerate(table.pools)],
        "random_sequence": table.random_sequence,
        "table": table.id,
    }


def table_id_from_file(rel: str) -> str:
    """`.../data/minecraft/loot_table/blocks/stone.json` → `minecraft:blocks/stone`。"""
    for marker in ("/loot_table/", "/loot_tables/"):
        if marker in rel:
            head, _, tail = rel.partition(marker)
            return f"{head.rsplit('/', 1)[-1]}:{tail[:-5]}"
    return rel[:-5] if rel.endswith(".json") else rel
