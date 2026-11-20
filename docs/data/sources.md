# 来源与路线

上游可达性产物描述「拿得到、经由什么」，本文规定如何把它读成本模型的来源、路线与槽位。实现见 `src/bingo_grading/sources/` 与 `src/bingo_grading/recipes/`，两边不一致时以代码为准。

## 来源类别

`source_type` 取值固定为八种，由上游规则的 `family` 与战利品表路径共同判定。

| family | 附加条件 | source_type |
|---|---|---|
| `loot` | 表路径以 `blocks/` 开头 | `block_drop` |
| `loot` | `entities/` 或 `charged_creeper/` | `mob_drop` |
| `loot` | `harvest/`、`carve/`、`till/` | `block_drop` |
| `loot` | `shearing/` | `shear` |
| `loot` | `archaeology/`、`pots/` | `suspicious_block` |
| `loot` | `chests/`、`barrels/`、`dispensers/`、`equipment/`、`spawners/`、`gameplay/`、`brush/` | `loot_table` |
| `trades` | — | `trade` |
| `code/drops_source`、`code/death_drops`、`code/mob_buckets`、`bridge/entity_behaviour` | — | `mob_drop` |
| `code/fluid_buckets` | — | `fill` |
| `code/structure_gadgets`、`bindings/template_item` | — | `loot_table` |
| `bridge/item_conversion` | — | `convert` |
| `recipes` | — | 不产生来源行 |

未登记的 `family` 不猜：计入 `unmapped_family` 并输出到构建摘要，不生成来源行。

## 来源行字段

索引是 JSONL，第一行是头部（`index_schema`、`label`、计数），其余每行一条来源。

| 字段 | 含义 |
|---|---|
| `item` | 物品命名空间 ID |
| `source_type` | 来源类别 |
| `subject` | 来源的直接对象 |
| `stat_subject` | 查世界统计的键，见下节；未映射为 `null` |
| `structure_set` | 战利品表对应的结构集合，非结构来源为 `null` |
| `route` | 行动路线 |
| `hard_prereq` | 硬前置叶子节点 |
| `biomes` | 上游 `worldgen` 规则里出现的群系 |
| `notes` | 无法归类的中间节点（`item:` / `tag:` / `flag:`） |
| `cycles` | 闭包展开时遇到的环 |
| `probabilistic` | 是否概率性来源 |
| `probability` | 概率值，未登记为 `null` |
| `is_reverse` | 是否反向合成边，第一版恒为 `false` |
| `primary_source_hint` | 主来源提示，第一版恒为 `null` |
| `rule_ref` | 上游规则 ID，用于追溯 |
| `family` | 上游规则族 |
| `truncated` | 闭包是否撞到节点上限 |

## 硬前置

`hard_prereq` 是上游规则 `body` 的递归闭包，只保留可归类的叶子。递归沿上游同 head 规则展开，按前缀分流：

| 前缀 | 处理 |
|---|---|
| `world:` `structure:` `tool:` `station:` `assume:` `enchant:` | 叶子，收集 |
| `table:` `block:` `entity:` | 展开 |
| `item:` `tag:` `flag:` | 不展开，进 `notes` |

`item:` 不展开：它是链式前置（要绿宝石），属于策略，不是「顺手能到」的世界条件；展开它会把合成树整棵拉进来，与合成展开器重复计代价。

递归遇环时记录到 `cycles` 并跳过该分支。单条来源的闭包上限是 256 个节点、深度 12，撞上限时 `truncated` 为真。

## 来源对象与统计键

`subject` 是来源的直接对象：

- `block_drop` / `shear` / `suspicious_block`：方块 ID（`minecraft:redstone_ore`）
- `mob_drop`：实体 ID（`minecraft:zombie`）
- `trade`：`<职业>/<等级>`（`cleric/1`）
- `loot_table`：战利品表路径（`minecraft:chests/simple_dungeon`）

`stat_subject` 是查世界统计的键，与 `subject` 不一定相同（[ADR 0011](adr/0011-measurement-identity-vs-source-identity.md)）：

| 来源类别 | `stat_subject` |
|---|---|
| `block_drop` | 同 `subject` |
| `mob_drop` / `shear` | 基础实体 ID，去掉变体后缀（`minecraft:sheep/black` → `minecraft:sheep`） |
| `loot_table` / `suspicious_block` | 结构集合 ID，由 `data/knowledge/structure_sets.toml` 最长前缀匹配；匹配不到为 `null` |

上游的箱子桥接只给 `assume:structure_loot`，结构身份只在表路径里。因此结构的到达代价按 `stat_subject`（结构集合）查统计，不按 `hard_prereq`。

`null` 意味着这条来源查不到统计，会出现在缺口报告里，不会被静默当成有数据。战利品表里没有列出的路径（`bastion_*`、`end_city_treasure`、`simple_dungeon`、`spawn_bonus_chest`、各类 `gameplay/`）都不是结构集合，故意不映射。

## 行动路线

`route` 取值四种：`surface`、`underground`、`branch_mine`、`other_dimension`。判定顺序：

1. `subject` 命中维度关键词表 → `other_dimension`。
2. `hard_prereq` 含下界或末地世界节点 → `other_dimension`。
3. `source_type` 为 `block_drop` / `shear` / `suspicious_block`，且 `subject` 属于地下方块集合 → `underground`。
4. `source_type` 为 `loot_table` / `suspicious_block`，且 `subject` 属于地下结构集合 → `underground`。
5. **方块只由结构模板放置（无世界生成特性）**，且模板所属结构集合属于地下集合 → `underground`。
6. 其余 → `surface`。

第 5 条的依据是 `src/bingo_grading/sources/placement.py`：方块的地理属性从**放置事实**读，不从战利品表路径推断。只认两类放置事实（`worldgen` 且 `slot=block`、`bindings/template_block`），玩家放置与方块转换一律不认——后者会成环（有红石就能放红石线）。详见 [ADR 0013](adr/0013-placement-facts-not-loot-paths.md)。

修之前，红石线的表在 `blocks/` 下被当成地表方块，实际它只由古代城市模板放置在 y≈-51。修复后 323 条来源被识别为「只由结构放置」，124 条从 `surface` 改判为 `underground`。

模板路径 → 结构集合的映射在 `data/knowledge/structure_sets.toml` 的 `[template_prefixes]`，与箱子表的 `[loot_prefixes]` 分开：前者对齐「方块被哪个结构放置」，后者对齐「箱子表属于哪个结构」。

`branch_mine` 是保留值，当前不产生：它描述玩家拿到工具后主动开展的挖掘策略，没有对应的来源判定规则。

## 合成展开

配方不产生来源行，但影响槽位：物品的槽位来自它自己的来源，以及沿配方链展开后的叶子来源。没有这一步，铁锭不会有「地下 × 挖掘」槽位——它自己只能被合成、被交易、被熔炼。

展开规则：

- 配方是 AND：输入里只要有一条不可得，整条配方路径不成立。没有这条规则，「铁锭 → 铁粒 → 铁镐 → 木棍」会把树叶算成铁锭的来源——铁镐本身要先有铁锭。
- `tag:` 输入是 OR：任一成员可得即成立。成员超过 6 个时只取前 6 个，记入 `tag_limited`。
- 嵌套 tag 递归展开。
- 深度上限 4、单物品叶子上限 2000。撞上限时保留已得部分并标记 `truncated`。
- 环（反向合成、回收链）在递归处自然终止，不单独维护强连通分量。

## 概率

上游按存在性语义求解，不记录概率。概率性来源在 `src/bingo_grading/gamedata.py` 的 `PROBABILITY_ROWS` 手工登记（8 条常量），键为 `(item, source_type, subject)`：

- 未登记 → `probabilistic = false`，`probability = null`。
- 登记 → `probabilistic = true`，`probability` 取表值，映射到 `variance_penalty`（[ADR 0009](adr/0009-probability-to-variance.md)）。

未登记不等于确定性。报告里的低覆盖物品清单是补表的待办。

## 反向边与主来源

`is_reverse` 只在合成配方上有意义，而配方不产生来源行。字段保留以便下游按同一契约读取，第一版恒为 `false`。

`primary_source_hint` 第一版恒为空。缺省时同一物品的所有来源权重相等；主来源筛选是下游权重问题。
