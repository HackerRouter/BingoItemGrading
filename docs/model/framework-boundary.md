# 数据源与框架边界

本文回答三个问题：数据从哪来、哪些进了框架、哪些仍是只为特定物品写的特例。

## 数据源清单

### 原版发布物：由 `bg data sync` 派生，不入库

`data/upstream/` 是派生数据：`bg data sync` 从 `config.yml` 指向的两个上游项目
（`RecipeAnalysis`、`WorldGenStatsCollector`）复制过来。不入库的理由很直接——入库等于自己维护一份副本，
上游更新后两边就分叉了。`bg data verify` 按 `manifest.json` 校验本地副本是否与源一致。
`data/knowledge/` 是人工维护的分类映射，上游没有对应物，必须入库；
`data/stats/` 由 `bg data ingest` 与 `bg data loot` 从 `data/upstream/` 加工出来，同样可重建，不入库。

| 数据 | 位置 | 规模 | 去向 |
|---|---|---|---|
| 战利品表 | `data/upstream/<pack>/datapack/data/minecraft/loot_table/` | 1447 张 | 全部进 `loot_expectation`（方块/生物/箱子/剪毛/刷扫） |
| 结构模板 | `data/upstream/<pack>/datapack/data/minecraft/structure/` | 1511 个 SNBT | 结构形状与箱子位置 |
| 其余类别 | 同上 `datapack/data/minecraft/*` | 42 类 | 暂不消费（worldgen 参数等只经采集侧变成统计值） |

地形包是增量补丁，启用哪些 overlay 由 `pack.mcmeta` 的区间声明与原版格式号共同决定。**这套合并已归 RecipeAnalysis**，产物是 `inputs/<pack>/datapack-merged/`，本项目只同步结果、不再保留包原件，见 [ADR 0029](../adr/0029-datapack-merge-owned-upstream.md)。地形包的 worldgen 参数（`noise_settings`、`placed_feature` 等）本项目不解析，它们只经采集侧变成统计值。

### 上游产物：已接入

> **目录布局（2026-11-21 起）**：RA 把 `output/<pack>/` 重新组织成四个子目录——
> `facts/`（IR 事实）、`export/`（结构清单、模板表、刷怪表、挖掘表）、
> `report/`（覆盖率、缺口、可达性、`harvest.jsonl`）、`paths/`（可视化图）；
> 根下只留 `graph.json` / `guide.md` / `profile.json`。
> 本侧取路径只走 `paths.recipe_facts()` / `recipe_export()` / `recipe_report()`，
> 不要在别处硬拼文件名——之前的布局是这些表散在 output 根下，改一次就要全仓找。

| 产物 | 规模 | 进入的 stat_type |
|---|---|---|
| `graph.json` | 3.1 MB，17335 条规则 | 不进统计层，进 `sources` / `slots` |
| `facts/template.jsonl` | 2.1 MB | 结构箱子构成 → `loot_expectation` |
| `section-block-histogram.json` | 437 KB | `block_density` |
| `ore-stats.<dimension>.json` | 1.0 MB | `ore_density`、`ore_exposure` |
| `structure-spacing.json` | 18 KB | `structure_density` |
| `lava-lakes.json` | 11 KB | `structure_density` |
| `entity-census.json` | 22 KB | `mob_density` |
| `biome-histogram.json` / `biome-patch.json` | 108 KB | `spawn_distribution`、`biome_patch` |
| `report/harvest.jsonl` | 108 行 | 方块 → 最低工具等级 / 最弱合格工具（由 RA 的 `minecraft:tool` 组件 + `needs_*_tool` 标签推出） |
| `facts/mining.jsonl` | 416 KB，1286 行 | **方块属性**：`hardness`、`requires_correct_tool`、`explosion_resistance` → 破坏秒数与工具要求（`mining_facts.py`） |
| `export/mining_tool_materials.jsonl` | 1.3 KB | 材质 → 挖掘速度（wood 2.0 … diamond 8.0）与等级门槛 |

### 上游产物：未接入

| 产物 | 规模 | 本该提供什么 |
|---|---|---|
| `facts/trade.jsonl` | 237 KB，459 条 | 交易条款：`wants` / `gives` / `meta.max_uses`（已接入 `trade_offer`） |
| `facts/recipe.jsonl` | 920 KB | 配方折算：金粒→锭、小麦→干草块、粘土球→块 |
| `facts/loot_table.jsonl` | 1.1 MB | 有意不用：按存在性语义丢弃了 `weight`，期望由本侧解析原版表算 |
| `facts/tag.jsonl` | 427 KB | 物品标签分组 |
| `facts/registry.jsonl` | 245 KB | 注册表内容 |
| `facts/block_transform.jsonl` | 87 KB | 方块状态与变换 |
| `facts/code_link.jsonl` | 367 KB | 代码链路 |
| `facts/components.jsonl` | 1.4 MB | 物品组件 |
| `facts/spawner_config.jsonl` | 9.7 KB | 刷怪配置 |
| `facts/worldgen.jsonl` | 864 KB | 世界生成参数 |
| `reachability.jsonl` / `ledger.jsonl` | 5.4 MB | 可达性明细与求解账本 |

### 手工知识表与内置常量

| 来源 | 内容 |
|---|---|
| `src/bingo_grading/gamedata.py::PROBABILITY_ROWS` | 8 条路线概率（原 `probabilities.toml` 已并入） |
| `data/knowledge/routes.toml` | 地下方块、地下结构前缀、维度关键词的分类清单 |
| `data/knowledge/structure_sets.toml` | 25 条战利品前缀 → 17 个结构集合 |

### 代码内常量（按流程层找入口）

「补充游戏数据」全部在 **`src/bingo_grading/gamedata.py`**：一个零依赖的叶子模块，
按**主题**分八区（玩家操作时间 / 等待节奏 / 游戏机制 / 模型规模 / 结构事实 /
世界事实 / 方块与工序时长 / 概率登记）。所有层都引用它，不存在「同一个数两处各存一份」。

编码依赖（能力名、`action_id` 前缀、类别词汇表、构造表、TU 定义与评分档位）
留在各自模块——那些改错了要跟代码一起改，是不一样的东西。

| 模块 | 编码依赖 |
|---|---|
| 统计契约 | `stats/model.py`（`SPATIAL_TYPES` / `FACT_TYPES` / `STAT_VALUE_SCHEMA`） |
| 来源索引 | `sources/constants.py`（类别词汇表、族映射、产物版本号） |
| 动作图 | `sources/actions/common.py`（递归上限、序列化器、节点型来源表）、`sources/constructs.py`（能力名与构造表） |
| 求解 | `plan/actions.py`（`once` / `per_use` 词汇表）、各模块内部阈值 |
| 评分 | `units.py`（TU 定义、时间档位、`FREE_COVERAGE` / `VARIANCE_PENALTY`） |

**头部还有一项 `missing_prereqs`**：动作的前置指向一个「图上没有任何产出」的物品。这类动作会被
`tiers` 判成 `no_rule` 后**静默丢弃**，所以构建时单独记账，`bg doctor` 的 `actions` 检查非空即报红。
典型诱因是名字拼错（工具名曾写成 `wood_pickaxe`，正确是 `wooden_pickaxe`，导致所有石头类挖矿路线消失），
另一个是上游新增了需求而本侧没接上。`capability:` 前缀不参与这项检查——那是状态，由 `uncovered` 记账。

## 框架覆盖范围

判定依据：模块内是否出现具体物品 ID。

| 模块 | 物品特例 | 作用 |
|---|---|---|
| `paths.py` / `upstream.py` | 无 | 数据定位与同步（overlay 合并由上游完成） |
| `data/stats/`（model、store、resolver、index、importers） | 无 | 统计模型、回退链、五类产物导入 |
| `loot/`（tables、expect） | 无 | 战利品分层加载、期望计算，含 `alternatives` / `modifier` / 工具条件 |
| `mining.py` | 无 | 密度行 → 挖掘代价 |
| `sources/`（graph、index、classify、closure、routes、placement、knowledge） | 无 | 来源索引、前件闭包、路线归类 |
| `recipes/expand.py` | 无 | 配方链展开 |
| `slots/`（`build`、`report`） | 无 | 槽位聚合与覆盖率 |
| `case/context/` | 无 | 9 个取数 mixin：`recipes`、`exposure`、`mining`、`structures`、`patches`、`content`、`loot`、`biomes`、`mobs` |

`case/context/` 零模块级常量，每个算子都从统计行取数并在 `Sourced` 里带出处——它是数据面与案例面之间唯一的接口。

## 常量的三类与去向

原则：**事实数据一律从可信来源取，不写常量。** 剩下的常量按性质分三类，处理方式不同：

| 类别 | 判据 | 现状 | 例 |
|---|---|---|---|
| 版本事实 | 原版机制，上游 `facts/recipe.jsonl` 里有 | **已接入**：`ctx.recipe_conversion()` / `recipe_ratio()` 直接读配方（产量 + 全部原料用量），**含 `#tag` 展开**；案例层不写折算数字 | 桶 = 3 铁；一次火焰弹配方出 3 个；9 粒 = 1 锭；1 干草块 = 9 小麦；铁镐 = 3 铁 + 2 木棍 |
| 世界事实 | 当前世界测得，`data/stats/<pack>/` 里有 | **已改为取数**，缺失时报缺口 | 村庄箱数 → `structure_content.containers_per_start`；村民数 → `mob_density`；金粒掉落 → `loot_expectation`；地牢箱数 → `structure_content` |
| 标定/策略 | 玩家行为或模型假设，没有可信数据源 | 集中在 `gamedata.py`，报告里标「标定值」 | `SECONDS_PER_TU`、`CHEST_SECONDS`、`VILLAGERS_RESERVED`、`LAVA_BLOCKS_PER_PATCH` |

硬规则：

1. **世界事实缺失时不填默认值**：该路线缺席，并把缺口写进 `assumptions`（例：村庄 `village_taiga` 的 `containers_per_start` 算成 0，只报缺口，不当 0 参与平均）。
2. 版本事实暂时硬编码的，必须集中在 `units.py` / 案例常量区，并补一条与上游数据一致性的测试；联入 `facts/recipe.jsonl` 后删除。
3. 标定参数只允许出现在 `gamedata.py`（游戏数据）与 `units.py`（TU 与评分口径），案例文件里不得出现算式。

组装面（专用 ID、动作声明、`race` 分组）仍然全是特例，集中在 `sources/actions/` 与 `case/sources/`；入口统一为 `case/registry.py` 的 `builder_for()`——任何物品都从来源索引自动拼图。手写案例（`case/gold.py` / `case/redstone.py` / `case/portal.py`）已于 2026-11-17 删除，`packs.py` 一并移除（overlay 合并由 RA 负责）。

## 完备度的判据

数值稳定不构成框架完备的证据。改动数据接线后红石与金锭的数值不变，只说明这两条线的结果由案例内的常量而非数据决定，恰恰是特例占主导的表现。

可执行的判据是**新增一个物品需要动多少代码**：

- 2026-11-12 之前：写一个新的 `case/<item>.py`，200 行上下，重新推导路线并把常量再抄一遍；同时在 `cmd_dag` 的字典里加一条。
- 现在：加数据不改代码。任何物品 `bg plan --item <任意>` 都从来源索引自动拼图，不再有手写案例。

完备度不再用「能不能算」判，改看每次求解的 `uncovered_total` 与 `gaps`——那是确实拿不到、或拿得到但没接进模型的来源条数。

**基准的边界**：`uncovered_total` 与动作图头部的 `no_action_items` 只覆盖「来源索引里有记录、但没翻译成动作」的部分。索引本身来自上游 RA 图，而「RA 图是否覆盖了全部可得来源」是上游的人工判断，本侧无法验证。因此：

- `source_index` 的物品集是**上游声称有来源的集合**，不是完整性证明；
- 本侧能保证的是「在这个基准下，每个物品要么有动作、要么有缺口原因」；
- 基准之外的遗漏，需要上游也做「规则 → 来源记录」的对账才能发现。

## 概率模型：统一到「每次触发的期望件数」

以前每行来源只有 `probabilistic` + `probability`，数值来自手工表
（现为 `sources/knowledge.py::PROBABILITY_ROWS`，8 条）。现在所有直接来源走同一个口径：**触发一次平均给出多少件**。

| 来源类别 | 触发方式 | 数据 |
|---|---|---|
| `block_drop` | `block_break` | 原版 `loot_table/blocks/` |
| `mob_drop` | `kill` | 原版 `loot_table/entities/` |
| `loot_table` | `chest_open` | 原版 `loot_table/chests/` + `template.jsonl` 的箱子构成 |
| `shear` | `shear` | 原版 `loot_table/shearing/` |
| `suspicious_block` | `brush` | 原版 `loot_table/archaeology|pots/` |

实测：3128 条来源里 2542 条有推导值，手工表命中数 0。剩下 586 条的分布就是缺口清单。
细节与判据见 [ADR 0027](../adr/0027-per-trigger-expectation.md)。

战利品表的语法解析与 RecipeAnalysis 共用 `src/mcshared/`（junction 拼到 `ra.mcshared`），
见 [ADR 0026](../adr/0026-shared-parsing-layer.md)。语义与概率不共用：上游按存在性求解，
本侧才计算数量。

## 缺口

按「接线成本」排序。

1. 交易层：`trade.jsonl` → `trade_offer` stat_type，暴露职业、等级、`wants`、`gives`、`max_uses`。
   这是剩下 586 条无推导来源里的主体。
2. ~~方块掉落层~~：已完成。原版 `loot_table/blocks|entities|shearing|archaeology`
   全部进 `loot_expectation`；案例层已改为从 `loot_expectation` 取数，手写掉落常量随案例删除。
3. 折算层：`recipe.jsonl` → `item_convert` stat_type，提供「A 换 B 的比例」，取代手写的单位换算。
4. 结构内部：需要上游新增 `structure-interior` 分析器，要求见[上游数据需求](../contracts/upstream-requirements.md)。
   替代「全图总量 ÷ 结构数」的反推与 `CHESTS_PER_VILLAGE`。
5. ~~策略注册~~：已完成。`case/registry.py::builder_for()` 对任意物品走 `sources/actions/build()`，来源族在 `build._HANDLERS` 登记。
6. 标定隔离：`SECONDS_PER_TRADE`、`SECONDS_PER_CHEST`、`HAY_FIND_SECONDS` 一类集中到 `data/knowledge/timing.toml`，诊断输出标记为 `calibration`。

前 3 项的数据已在上游产物中且格式已验证，属于纯接线；第 4 项需要采集侧新增分析器；第 5、6 项是案例层的结构改造。
