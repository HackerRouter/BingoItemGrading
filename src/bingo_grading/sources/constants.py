"""来源索引层的常量区。

只放字面量：字符串、数值、集合、映射表。这里不 import 任何业务模块，
所以谁都能引用它而不产生循环。

放进来的判据是**跨模块共享**或**用来对账**——版本号、类别词汇表、判据映射。
只服务单个函数内部的阈值（`closure.MAX_NODES`、`plan/supply.EPS` 之类）留在原模块，
免得这个文件变成杂物箱。

其他常量入口（**游戏数据**与**编码依赖**分两类，别混放）：

- **游戏数据**（事实/标定值/形状/概率）全部在 `src/bingo_grading/gamedata.py`，
  按主题分八区；所有层都引用它，不再按流程层分开。
- **编码依赖**留在各自模块：本文件（类别词汇表）、`sources/actions/constants.py`、
  `sources/constructs.py`（能力名与构造表）、`plan/actions.py`（词汇表）、
  `stats/model.py`（形状契约）、`units.py`（TU 与评分档位）。
"""

from __future__ import annotations

# ============================================================ 产物契约版本

# 上游 `graph.json` 的 `graph_schema`。不认识就报错，不尽力解析。
GRAPH_SCHEMA = 1

# `source_index.jsonl` 的头部版本。增删列就加一。
INDEX_VERSION = 1
# 2：加入 `stat_subject` / `structure_set`。字段变化即 +1。
# 3：加入 `yield_per_trigger` / `yield_source`（概率改由战利品表推导）。
INDEX_SCHEMA = 3

# ============================================================ 来源类别

# 战利品表路径的第二级（`blocks` / `chests` / …）→ 来源类别。
LOOT_PREFIX_TYPES: dict[str, str] = {
    "blocks": "block_drop",
    "harvest": "block_drop",
    "carve": "block_drop",
    "till": "block_drop",
    "entities": "mob_drop",
    "charged_creeper": "mob_drop",
    "shearing": "shear",
    "archaeology": "suspicious_block",
    "pots": "suspicious_block",
    "chests": "loot_table",
    "barrels": "loot_table",
    "dispensers": "loot_table",
    "equipment": "loot_table",
    "spawners": "loot_table",
    "gameplay": "loot_table",
    "brush": "loot_table",
}

# 非战利品表族 → 来源类别。
FAMILY_TYPES: dict[str, str] = {
    "trades": "trade",
    "code/drops_source": "mob_drop",
    "code/death_drops": "mob_drop",
    "code/mob_buckets": "mob_drop",
    "bridge/entity_behaviour": "mob_drop",
    # 拿空容器装流体/半流体（水、岩浆、细雪）。上游把它登记成 `block_drop`
    # （「挖了掉自己」），但这三种都**挖不下来**：水与岩浆没有掉落，细雪方块被
    # 破坏时什么都不掉，只能用空桶右键装。所以单独立一类。
    "code/fluid_buckets": "fill",
    "code/structure_gadgets": "loot_table",
    "bindings/template_item": "loot_table",
    # 手持物品用一下就变成另一个物品（空地图 → 已填充地图、书与笔 → 成书）。
    # 不是合成台配方，也没有战利品表：输入被消耗、当场换物品。
    "bridge/item_conversion": "convert",
}

SOURCE_TYPES = (
    "block_drop",
    "mob_drop",
    "trade",
    "loot_table",
    "suspicious_block",
    "shear",
    "convert",
    "fill",
)

# 不产生来源行的族。
SYNTHETIC_FAMILIES = frozenset({"recipes"})

# 来源类别 → 触发方式。与 `stats/importers/loot.py` 的 `TRIGGER_BY_PREFIX` 一一对应：
# 前者按图上的来源类别命名，后者按战利品表目录名命名，指的是同一件事。
TRIGGER_BY_SOURCE: dict[str, str] = {
    "block_drop": "block_break",
    "mob_drop": "kill",
    "shear": "shear",
    "suspicious_block": "brush",
    "loot_table": "chest_open",
}

# ============================================================ 行动路线

# 槽位生成器与来源索引共用这套名字，别各写一份。
ROUTES = ("surface", "underground", "branch_mine", "other_dimension")

OTHER_DIMENSION_WORLDS = frozenset({"world:minecraft:the_nether", "world:minecraft:the_end"})

# ============================================================ 前件闭包

LEAF_PREFIXES = frozenset({"world", "structure", "tool", "station", "assume", "enchant"})
EXPAND_PREFIXES = frozenset({"table", "block", "entity"})

# `worldgen` 规则把群系写在 `meta.source = "biome/<id>"` 里。
BIOME_SOURCE_PREFIX = "biome/"

# ============================================================ 放置事实

TEMPLATE_FAMILY = "bindings/template_block"
WORLDGEN_FAMILY = "worldgen"

# ============================================================ 手工登记的数值

# 游戏数据不在这里：概率、方块集合、时长都归 `gamedata.py`（那里按主题分区）。
# 本文件只放编码依赖——改了要跟代码一起改的词汇表、映射与版本号。
