"""上游规则 → 来源类别。

判定只用两样东西：`family` 与战利品表路径前缀。两者都在上游产物里显式存在，
不需要从物品名或方块名猜。

未登记的 `family` 返回 `None`：调用方把它计入 `unmapped_family` 并写进覆盖率
报告，不猜成某个默认类别。
"""

from __future__ import annotations

from .constants import FAMILY_TYPES, LOOT_PREFIX_TYPES, SYNTHETIC_FAMILIES
from .graph import Rule


def loot_prefix(table: str) -> str:
    """`minecraft:chests/simple_dungeon` → `chests`。"""
    _, _, rest = table.partition(":")
    return rest.split("/", 1)[0] if "/" in rest else rest


def classify(rule: Rule) -> str | None:
    """来源类别；`None` 表示该规则不产生来源行。"""
    if rule.family in SYNTHETIC_FAMILIES:
        return None
    if rule.family == "loot":
        table = rule.meta.get("table")
        if isinstance(table, str):
            return LOOT_PREFIX_TYPES.get(loot_prefix(table), "loot_table")
        return "loot_table"
    return FAMILY_TYPES.get(rule.family)


def subject_of(rule: Rule, source_type: str) -> str:
    """来源的直接对象。优先取 body 里的方块/实体节点，其次从表路径推。"""
    wanted = {
        "block_drop": "block",
        "shear": "block",
        "suspicious_block": "block",
        "mob_drop": "entity",
        # 转换的输入物品：`map` → `filled_map` 取的是 body 里的 `item:minecraft:map`。
        "convert": "item",
        # 装流体取的是目标方块：`bucket + block:minecraft:powder_snow`。
        "fill": "block",
    }
    prefix = wanted.get(source_type)
    if prefix is not None:
        for node in rule.body:
            if node.startswith(f"{prefix}:"):
                return node.split(":", 1)[1]

    table = rule.meta.get("table")
    if isinstance(table, str):
        if source_type in ("block_drop", "shear", "suspicious_block", "mob_drop"):
            return _subject_from_table(table)
        return table

    if source_type == "trade":
        profession = rule.meta.get("profession")
        if isinstance(profession, str):
            level = rule.meta.get("level")
            if isinstance(level, (int, str)):
                return f"{profession}/{level}"
            # 没有等级的报价（流浪商人就是这类）：按职业聚合，
            # 不能退回 `rule.id`——那会变成 `trade:data/.../*.json` 文件路径，
            # 下游 `_offers_for` 拿它去匹配 `trade_offer` 的 subject 永远查不到。
            return profession
        # 共享报价组：一个文件被多个职业共用时 `profession` 是 null，
        # 适用职业列在 `applies_to` 里，`trade` 字段形如
        # `minecraft:smith/1/coal_emerald`。这里取组名与等级，
        # 由 `actions/trade.TRADE_ALIASES` 展开成真实职业；
        # 仍然不能退回 `rule.id`（见上）。
        trade = rule.meta.get("trade")
        if isinstance(trade, str):
            _, _, rest = trade.partition(":")
            parts = rest.split("/")
            if len(parts) >= 2 and parts[0] and parts[1]:
                return f"{parts[0]}/{parts[1]}"
    return rule.id


# 这些前缀下的子路径会撞名：`chests/trial_chambers/corridor` 与
# `pots/trial_chambers/corridor` 剥掉前缀后都叫 `trial_chambers/corridor`，
# 而 `loot_expectation` 里同名的只有完整路径。剥了前缀就一条也对不上。
#
# `charged_creeper` 同理，而且更糟：`charged_creeper/creeper` 剥成 `creeper`
# 会撞上 `entities/creeper`（那边只有火药），于是头颅类物品查期望时拿到的是
# 苦力怕的普通掉落表，`creeper_head` / `zombie_head` / `piglin_head` 全部无来源。
KEEP_PREFIXES = frozenset(
    {"pots", "dispensers", "equipment", "spawners", "charged_creeper"}
)


def _subject_from_table(table: str) -> str:
    """`minecraft:blocks/redstone_ore` → `minecraft:redstone_ore`。

    表路径的第二级就是对象名，这是上游 `bridge/table` 的目录约定。
    但有些目录下的第二级不唯一（见 `KEEP_PREFIXES`），那些保留完整路径。
    """
    namespace, _, rest = table.partition(":")
    if "/" not in rest:
        return table
    head, _, tail = rest.partition("/")
    if head in KEEP_PREFIXES:
        return table
    return f"{namespace}:{tail}"
