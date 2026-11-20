"""结构模板的 SNBT 解析与语法归一。

结构模板的第一手是服务端 jar 内层的 `.nbt`，由 datagen 的 `--dev` 转成文本 SNBT；
反编译源码树里的同名副本 palette 被抹空，不能作为方块身份来源。两种来源都由调用方
解码成文本再交给这里。

只取四样东西：

- `data[].state` → 方块（palette 条目的引用）
- `data[].nbt.LootTable` 与空的 `nbt.Items` → 战利品容器（表可由运行时填）
- `data[].nbt.pool` → 拼图池
- `entities[]` → 内嵌实体（含装备与手上的物品）

`palette` 全空但格子非空时记 `blocks_unreadable`：那是来源缺了方块身份，
不是「结构里没有方块」。解析失败抛 `SnbtError`，不猜。

不引第三方 NBT 库：转换交给 jar 自带的 datagen（`--dev`），这里只读文本。
自写读取器比引入依赖便宜，且 `net.minecraft.data.Main` 已顺带做了
`DataFixTypes.STRUCTURE` 升级与 `packBlockState` 归一，那些才是不自写转换器的真正原因。
"""

from __future__ import annotations

from collections import Counter

SCHEMA_VERSION = 1


class SnbtError(ValueError):
    pass


# 能挂战利品表的方块实体（实现 `RandomizableContainer` 的那些）。
# `Items` 在别处也有：篝火、熔炉、高炉、烟熏炉、酿造台都带物品槽但不承载表，
# 混进来会让「每个结构几个箱子」偏大。
LOOT_CONTAINERS = frozenset(
    {
        "minecraft:barrel",
        "minecraft:chest",
        "minecraft:crafter",
        "minecraft:decorated_pot",
        "minecraft:dispenser",
        "minecraft:dropper",
        "minecraft:hopper",
        "minecraft:shulker_box",
        "minecraft:trapped_chest",
    }
)


class SnbtReader:
    """最小 SNBT 读取器：对象、数组、字符串、数字、布尔。

    只解析到「能当 dict / list / 标量用」为止，省略两样东西：
    一是数值的宽度与类型（`1b` / `1s` / `1f` 一律退化为 int 或 float），
    二是整型数组的类型前缀含义（`[I;` / `[L;` / `[B;` 统一当成 list），
    因为结构模板只用到方块名、物品 id 与槽位这些字符串与计数。
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def parse(self) -> object:
        value = self._value()
        self._ws()
        if self.pos != len(self.text):
            raise SnbtError(f"位置 {self.pos} 后有多余内容")
        return value

    def _ws(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos] in " \t\r\n":
            self.pos += 1

    def _value(self) -> object:
        self._ws()
        if self.pos >= len(self.text):
            raise SnbtError("意外结束")
        ch = self.text[self.pos]
        if ch == "{":
            return self._compound()
        if ch == "[":
            return self._list()
        if ch in "\"'":
            return self._quoted(ch)
        return self._bare()

    def _compound(self) -> dict:
        self.pos += 1  # {
        out: dict = {}
        while True:
            self._ws()
            if self.pos >= len(self.text):
                raise SnbtError("compound 未闭合")
            if self.text[self.pos] == "}":
                self.pos += 1
                return out
            key = self._key()
            self._ws()
            if self.pos >= len(self.text) or self.text[self.pos] != ":":
                raise SnbtError(f"键 {key!r} 后缺冒号")
            self.pos += 1
            out[key] = self._value()
            self._ws()
            if self.pos < len(self.text) and self.text[self.pos] == ",":
                self.pos += 1

    def _list(self) -> list:
        self.pos += 1  # [
        out: list = []
        # 类型前缀如 `[I;`、`[L;`、`[B;` 只在整型数组出现，这里按通用数组处理
        if self.pos + 1 < len(self.text) and self.text[self.pos] in "ILBX" and self.text[self.pos + 1] == ";":
            self.pos += 2
        while True:
            self._ws()
            if self.pos >= len(self.text):
                raise SnbtError("list 未闭合")
            if self.text[self.pos] == "]":
                self.pos += 1
                return out
            out.append(self._value())
            self._ws()
            if self.pos < len(self.text) and self.text[self.pos] == ",":
                self.pos += 1

    def _key(self) -> str:
        self._ws()
        if self.pos < len(self.text) and self.text[self.pos] in "\"'":
            ch = self.text[self.pos]
            return str(self._quoted(ch))
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] not in ":,{}[] \t\r\n":
            self.pos += 1
        if start == self.pos:
            raise SnbtError("空键")
        return self.text[start : self.pos]

    def _quoted(self, quote: str) -> str:
        self.pos += 1
        buf: list[str] = []
        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch == "\\" and self.pos + 1 < len(self.text):
                buf.append(self.text[self.pos + 1])
                self.pos += 2
                continue
            if ch == quote:
                self.pos += 1
                return "".join(buf)
            buf.append(ch)
            self.pos += 1
        raise SnbtError("字符串未闭合")

    def _bare(self) -> object:
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] not in ",}] \t\r\n":
            self.pos += 1
        token = self.text[start : self.pos]
        if not token:
            raise SnbtError("空值")
        # 数值后缀与布尔后缀都可能出现（`1b`、`false`），先去后缀再判
        lowered = token.rstrip("bBsSlLfFdD")
        if lowered in ("true", "false"):
            return lowered == "true"
        try:
            return int(lowered)
        except ValueError:
            pass
        try:
            return float(lowered)
        except ValueError:
            return token


def parse_snbt(text: str) -> object:
    return SnbtReader(text).parse()


# 方块实体 NBT 里「装着物品」的键。逐键列举而不是通配 `id`，
# 因为 `id` 在方块实体里是**方块实体类型**（`minecraft:decorated_pot`），
# 把它的值当物品会把整棵模板的方块实体都读成物品。
#
# | 键 | 载体 | 形状 |
# |---|---|---|
# | `sherds` | 饰纹陶罐 | `{back: {id: ...}, front: ...}` |
# | `Items` | 箱子 / 漏斗 / 发射器 | `[{slot, item: {id, count}}]` |
# | `item` | 物品展示框 / 盔甲架 | `{id, count}` |
# | `Book` | 讲台 | `{id: "minecraft:written_book", ...}` |
# | `RecordItem` | 唱片机 | `{id, count}` |
NBT_ITEM_KEYS = ("sherds", "Items", "item", "Book", "RecordItem")


def nbt_items(nbt: dict) -> list[tuple[str, str]]:
    """方块实体 NBT → `[(槽位名, 物品 id)]`。只取已知键，不递归猜。"""
    out: list[tuple[str, str]] = []
    for key in NBT_ITEM_KEYS:
        node = nbt.get(key)
        if node is None:
            continue
        for slot, ident in walk_item_slots(node, key):
            out.append((slot, ident))
    return out


def walk_item_slots(node: object, prefix: str) -> list[tuple[str, str]]:
    """在 `sherds` / `Items` 这类容器里找 `{id: "..."}` 形态的叶子。"""
    out: list[tuple[str, str]] = []
    if isinstance(node, dict):
        # `{"id": "minecraft:x", ...}` 是一个物品；`{"back": {...}}` 是分槽容器
        ident = node.get("id")
        if isinstance(ident, str) and ":" in ident:
            out.append((prefix, ident))
            return out
        for key, value in node.items():
            out.extend(walk_item_slots(value, f"{prefix}.{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            out.extend(walk_item_slots(value, f"{prefix}[{index}]"))
    return out


def template_id_from_file(file_label: str) -> str:
    """`data/<ns>/<模板目录>/x/y.snbt` → `x/y`。

    模板根之后的路径全部保留：模板自身可以含 `structures/` 这样的同名子目录
    （`ancient_city/structures/barracks`），按子串再切一次会截成裸名。
    运行期导出形态没有 `data/` 前缀，按「首段是模板目录」处理。
    """
    parts = (file_label[:-5] if file_label.endswith(".snbt") else file_label).split("/")
    if len(parts) >= 4 and parts[0] == "data":
        parts = parts[3:]
    elif len(parts) >= 2:
        parts = parts[1:]
    return "/".join(parts)


def normalize_template(doc: dict, template_id: str) -> tuple[dict, list[str]]:
    """模板 compound → `(payload, missing)`。

    `doc` 必须是已解析的 compound；顶层不是 compound 由调用方挡掉。
    """
    missing: list[str] = []
    blocks: list[str] = []
    block_entity_ids: list[str] = []
    # `structure_block{mode:data}` 的 `metadata`：模板里的「数据标记」。
    # 它是一类不以方块身份表达的机制：海军遗构的溺尸、船骸的三种箱子、末地城的哨兵，
    # 都是结构生成代码按标记名 `handleDataMarker` 决定的。标记名不在任何战利品表里，
    # 不取就只能看到一堆 `structure_block{mode:data}`，看不出那里会冒出什么。
    markers: list[str] = []
    marker_cells = 0
    # 全部容器格，`table` 为 null 表示表不在模板 NBT 里（由生成代码在运行时挂上）。
    # 只记有表的那些会让这类结构看起来「一个容器都没有」。
    containers: list[dict] = []
    pools: list[str] = []
    item_refs: list[dict] = []

    # 方块身份来自 `data[].state`（即 palette 条目）。第一手模板（jar 内层）
    # palette 完整；反编译源码树的副本被抹成空串，那种情况下只有带方块实体的
    # 格子还在 `nbt.id` 里保留了身份。
    # 两个来源必须分开记，否则下游会把「看不到」当成「没有」。
    palette = doc.get("palette")
    palette_filled = 0
    if isinstance(palette, list):
        palette_filled = sum(1 for item in palette if isinstance(item, str) and item)

    data = doc.get("data")
    if not isinstance(data, list):
        missing.append("缺少 data 数组")
        data = []
    for index, cell in enumerate(data):
        if not isinstance(cell, dict):
            missing.append(f"data[{index}] 不是 compound")
            continue
        state = cell.get("state")
        if isinstance(state, str) and state:
            blocks.append(state)
        nbt = cell.get("nbt")
        if isinstance(nbt, dict):
            cell_id = nbt.get("id")
            if isinstance(cell_id, str):
                block_entity_ids.append(cell_id)
            # 标记只看「有 metadata 的 structure_block」，不看方块名里的 `mode`：
            # `mode` 是状态、`metadata` 才是标记名，空串也是标记（名字没写）。
            if (
                isinstance(cell_id, str)
                and cell_id.split(":")[-1] == "structure_block"
                and "metadata" in nbt
            ):
                marker_cells += 1
                metadata = nbt.get("metadata")
                if isinstance(metadata, str) and metadata:
                    markers.append(metadata)
            table = nbt.get("LootTable")
            # 战利品容器有两种形态：带表引用，或物品槽空着等运行时填。
            # 物品槽已经填好的箱子不是战利品容器——那些内容已由 `item_refs` 逐件记录。
            if isinstance(table, str) or (
                cell_id in LOOT_CONTAINERS and not nbt.get("Items")
            ):
                containers.append(
                    {
                        "pos": cell.get("pos"),
                        "table": table if isinstance(table, str) else None,
                        "block_entity": cell_id if isinstance(cell_id, str) else None,
                    }
                )
            pool = nbt.get("pool")
            if isinstance(pool, str):
                pools.append(pool)
            for slot, item in nbt_items(nbt):
                item_refs.append(
                    {"holder": cell_id if isinstance(cell_id, str) else None, "slot": slot, "id": item}
                )

    # palette 全空但格子非空：普通方块身份不可得。
    # 这不是解析失败，而是来源缺陷，必须显式说清。
    blocks_unreadable = bool(data) and palette_filled == 0

    entities: list[dict] = []
    raw_entities = doc.get("entities")
    if isinstance(raw_entities, list):
        for index, ent in enumerate(raw_entities):
            if not isinstance(ent, dict):
                missing.append(f"entities[{index}] 不是 compound")
                continue
            nbt = ent.get("nbt")
            entities.append(
                {
                    "blockPos": ent.get("blockPos"),
                    "id": nbt.get("id") if isinstance(nbt, dict) else None,
                    "has_equipment": bool(
                        isinstance(nbt, dict)
                        and (nbt.get("ArmorItems") or nbt.get("HandItems"))
                    ),
                }
            )

    payload = {
        "template": template_id,
        "size": doc.get("size"),
        "data_version": doc.get("DataVersion"),
        "palette_size": len(palette) if isinstance(palette, list) else None,
        "palette_filled": palette_filled,
        "blocks": sorted(set(blocks)),
        "block_counts": dict(sorted(Counter(blocks).items())),
        "block_count": len(blocks),
        "block_entity_ids": sorted(set(block_entity_ids)),
        "blocks_unreadable": blocks_unreadable,
        # 标记名去重排序（白名单语义）；`marker_cells` 是带 metadata 的格子数，
        # 用于 palette 不可读时仍能给出「这里有几处标记」。
        "markers": sorted(set(markers)),
        "marker_cells": marker_cells,
        "containers": containers,
        "container_count": len(containers),
        # 有表的容器另列一份：既有消费方按「一行必带表」读取，形状不变。
        "loot_tables": [dict(item) for item in containers if item["table"]],
        "jigsaw_pools": pools,
        "item_refs": item_refs,
        "entities": entities,
    }
    return payload, missing
