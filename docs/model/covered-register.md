# 已补缺口索引

本文只记**已经补上**的缺口与它们的落地方式。未补的缺口、影响范围与待提交的新需求
见 [`gap-register.md`](gap-register.md)。

保留这份索引的理由：下游的每个数字都依赖某条上游字段，出问题时需要能立刻查到
「这个字段是哪次改动给的、当时怎么验收的」。

## 1. 上游 · 世界统计（C 系列）

来源契约见 [`collector-requirements.md`](../contracts/collector-contract.md)。

| # | 缺口 | 落地方式 |
|---|---|---|
| C1 | 产物不含版本/种子/地形包身份 | `target` 头部 |
| C2 | 种子为空、不可复现 | `seedMode` + 实际种子落盘 |
| C3 | `result` 不分维度 | 按维度嵌套 |
| C4 | `area` 是人读字符串 | `range` / `rangeByDimension` |
| C5 | 单位只写在散文里 | `units` 对象 |
| C6 | 缺群系斑块分析器 | `biome-patch` |
| C7 | 矿石暴露没有群系轴 | 独立分析器 `biome-ore` |
| C8 | 只预生成主世界 | 三维度各有 `ore-stats.<dim>` 与 `structure-interior.<dim>` |
| C13 | 非矿石方块无群系密度 | `section-block-histogram` → `block_density` |
| C14 | 非矿石方块无暴露率 | `cave-exposure` → `block_exposure`（天空/洞穴拆开） |
| C15 | 地牢未按高度拆分 | `dungeons.byDepth` |
| C16 | 结构箱数覆盖 13/53 | 覆盖升到 54/58 |
| C17 | 敌对生物没有 `mob_density` | ❌ 撤回（静态扫描给不出可信值）→ 转为新需求 C19 |
| C18 | 结构内方块与下界方块没有 `block_density` | 由 C16 的 `blocksPerStart` 顺带解决 |
| C19 | 结构的生物生成规则 | `spawn_tables.jsonl`（887 行）→ `mob_spawn` stat_type（850 行） |

不阻塞、未实现的：C9（稀有群系样本不足，下游改按 `total_blocks` 判可用性）、
C10（矿石密度无纵段分解，与未补的 D1 相关）、C11（无空洞率，改用体积占比法绕过）、
C12（结构间距只有全域值）。

## 2. 上游 · 配方与结构解析（R 系列）

| # | 缺口 | 验收依据（2026-11-13 实测） |
|---|---|---|
| R1 | 战利品条目缺 `weight` | `facts/loot_table.jsonl` 带 `weight` 的条目 **645** 条，等于验收标准 |
| R4 | 模板箱数/主体标记 | `template.jsonl` 已有 `container_count` 与 `jigsaw_pools`，是等价物 |
| R5 | `replaceable_blocks` 产假关联 | 全库 `replaceable_blocks` 引用数 **0** |
| R6 | 末地特性挂 overworld 节点 | 设计上接受，下游靠结构节点推维度 |

未完成：R2（`group_kind`/`group_id` 只覆盖 80 行）、R3（`minecraft:uniform` 噪声仍有
198 处）、R7（processor 放置的容器，见 gap-register 的 H3）。

## 3. 下游建模层（2026-11-11 ～ 11-13）

| 项 | 做法 | 效果 |
|---|---|---|
| 统一入口 | `sources/actions.py` 从 `source_index.jsonl` 自动拼动作图 | 任何物品都能算，不必逐条写代码 |
| 节点型来源 | 钓鱼 / 猪灵交易 / 礼物 / 出生箱 / 陶罐 / 猫 / 海龟成长 / 嗅探兽刨地 | 非结构来源全部接上 |
| 构造模型 | `sources/constructs.py`：下界门两条、末地门、桶、打火石、龙息 | 能力也有来源，递归定价 |
| 箱子口径 | 分表箱数（`loot_tables_per_site`）+ 行程按 `per_use` | `netherite_ingot` 9.17 → 45 |
| 维度感知 | `block_dimension` / `structure_dimension` | 下界矿石路线不再缺席 |
| 结构搜索 | 地牢用体积占比法 | 与手写 case 的 13.6 一致 |
| 挖矿的群系口径 | 默认「就地挖」（所有群系按 `equivalent_chunks` 加权合并）；只有 `BIOME_SPECIFIC_ORES` 那 4 种允许专门去某群系并付路费 | `coal` 挖煤 4.74 → 12.96（改走箱子 6.54）、`diamond_ore` 不再被当成便宜来源 |
| 矿物暴露率 | `ore_exposure.avgAirExposed` → `_ore_cave_parts()`，矿石终于是有 `mine:cave:` | `diamond` 26.01 → **9.55**、`coal` 6.54 → 3.05 |
| 竖井 | `data/knowledge/[structure_depths]` + `descend_cost` | 试炼大厅从「地表跑 150 格」变成「+83 格竖井」 |
| 首件口径 | `bg grade`（`whole_cost_tu`） | 一趟 100 个箱子不再摊成每件几分钱 |
| 整次递归 | 前置也按整次求价 | `ender_eye` 19.85 → 28.22 |
| 缺口报告 | 6 类误报修完 | `uncovered` 从 12–24 种降到 9–15 种 |
| 结构刷怪 | `spawn_tables` 的 `structure:*` 权重 ÷ 同类别总和 | `prismarine_shard` `inf` → 75.89 |
| 袭击按波次 | `wave_counts` 逐波累加，打到目标出现的波就收工 | `totem_of_undying` `inf` → 26.80（打完整场则 11.73 摊） |
| 交易按经验 | 每级反复成交该级报价，攒够 `VILLAGER_LEVEL_XP` 的档差 | `cleric/4` 150.79 → 43.43 |
| 等级能力 | 升级成本走 `capability:villager:<职业>/<级>` 的 `once`，不并进单价 | 买第 2、3 件不再重付升级费 |
| 卖货抵扣 | `gives` 是绿宝石的报价记负需求 | 卖 32 腐肉换 1 绿宝石 → 升级只要腐肉 |
| 刷怪表口径 | 同类别（`monster`/`creature`）才求权重和 | 不同刷怪上限不共用名额，混算会把机率押低 |
| 痟鱼桶 | `code/mob_buckets` + 群系斑块占比算「找水」 | 4 种鱼桶从 `none` 变成 2.88–3.87（原本只能跟渔夫买 5.71） |
| 组合需求 | `bg grade --together`：同一趟的产出共享行程 | 钻石+金锭+铁锭 17.79 → 11.38（一趟埋藏宝藏就齐） |

## 3.1 方块来源的多路并列（2026-11-15）

一个方块可以同时有结构放置 / 地表露头 / 洞穴暴露 / 散点矿四条来源，
`_block()` 全部并列 emit，由引擎按成本挑，不用 `if not made` 表达优先级。

| 项 | 做法 | 效果 |
|---|---|---|
| 来源并列 | 结构来源无条件并列（原来是「其他都不出活才兜底」） | `glow_lichen` 437 → **6.61**、`sculk_shrieker` 167212 → **1790** |
| 结构行程按趟 | 第一趟挂 `capability:<structure>` 的 `once`；`cost` 只补收超出一处产能的趟数 | 铜锭 0.05 → 6.50、煤块从「一趟无限出」修正为「一趟 0.83 个」 |
| 动作 ID 按物品去重 | `emit()` 撞 ID 且物品不同时改名 `...@<物品>` 保留 | 来源数不再随 `max_depth` 变；`raw_iron` 55.86 → **4.86**，45 件原不可得的方块掉落恢复 |
| 二维搜索的掉率 | `_search_blocks` 补 `entries_per_block`：`blocks = batch ÷ 每块掉率` | 苹果 0.09 → **2.59**、树苗 1.29、小麦种子 0.31 |
| 压缩方块 | 配方里 ≥4 个同一原料 → 不作散点矿（煤块/钻石块/铁块不自然生成） | `coal` 不再被 9 煤/块的拆解路线拉到 1.35 |
| 结构方块口径 | `structure_content.blocks_per_start` 按 `value["source"]` 分：有模板行的变体不用实测行（实测行是包围盒内全部方块，含地形） | `coal_ore` 不再有「跑一趟村庄拿 17 个」；模板口径覆盖 15→**18**/53 |
| 斧头刮蜡 | `facts/block_transform.jsonl` 的 `wax_off` 规则 → `waxed_X → X`，成本一次右键 | `oxidized_copper_door` 不可得 → **20.13**、`oxidized_copper_trapdoor` 1790 → **20.13** |
| 方块变换（`transmutes`） | 读 `graph.json` 的 273 条 `transmutes` 边：`code/transform`（刮蜡/去氧化/去皮）+ `bridge/convention`（粉末遇水固化）；`tool:` 是类别，映射成最弱工具 | 16 色混凝土不可得 → 3.2～5.1；`weathered_copper_door` → 21.94；全库新增可得 **88** |

已知未解决：只由结构分布、又没有配方的方块（`cobweb`、`torch`）仍会被当成散点密度。

| 凋灵召唤 | `constructs` 加 `wither:summon`（同末地门那套） | `nether_star` `inf` → 2063.27（骷髅头 692.14 × 3） |
| 紫水晶洞 | 挖到第一块洞壁就采整窝，不按 `1/ρ` 外推 | `amethyst_shard` 133.33 → **24.33** |
| 剪羊毛 | `shear` 触发 + 羊的密度（掉落表已有 2.0/次） | `white_wool`：1~3 个杀羊 2.21/个，4 个起剪毛（7.50 起，边际 0.964） |
| 挤奶 | `bridge/entity_behaviour`：容器对生物用一下 | `milk_bucket` → 3.40 |
| 取蜜 | 蜂巢的区块密度 → 搜索距离，玻璃瓶对蜂巢 | `honey_bottle` 152.89 → **4.85** |
| 直方图阈值 | 0.01 → 1e-4，放行稀有但真实的方块 | `block_density` 591 → 772 行（含 `bee_nest`） || 群系自然刷 | 刷怪表权重占比 → 平均打死几只，乘「等一只 + 打死一只」 | `ghast_tear` `inf` → 30.42；`ink_sac` 37.97 → 1.98 |
| 装备掉落 | `PROBABILITY_ROWS` 兼容层：`P(手持) × P(掉落)`，`_mob()` 在无 `loot_expectation` 时退到它 | `trident` 补上溺尸路线（239–592 TU，仍输给试炼大厅 305） |
| 权重来源的产出 | 打死 `W/w` 只里只有一只是目标，产出取 `per_kill` 不是 `kills × per_kill` | `wither_skeleton_skull` 230.55 → **692.14**，`nether_star` ×3.1 |
### 三处「有顺序」的来源不能摊平

袭击与交易都是**逐层累加**的，把最后一层的产出摊到前面会低两个档次：

| 来源 | 累加单位 | 为每个截断点各造一个动作 |
|---|---|---|
| 袭击 | 波次 | `raid:…:w5` / `w6` / `w7` 三条，成本递增、产出递增 |
| 村民交易 | 等级 + 每次成交的经验 | 每级每条报价各一条 `train:`，产出同一个等级能力 |

升级的经验阈值是 vanilla 机制（`tuning.VILLAGER_LEVEL_XP`）：
1～5 级累计 0 / 10 / 70 / 150 / 250，所以四段档差是 10 / 60 / 80 / 100。
每次成交给多少经验由数据给（`trade_offer` 的 `offer["xp"]`，2–30；
**省略字段时用 codec 默认值 1**，见 `collector-requirements.md` 的 C20），
单条报价的成交次数受 `max_uses` 限制（多为 12/16，缺省 4，刷满要换下一条）。

### 村民升级的三个设计点

这三条都是踩过坑才定下来的：

1. **等级是一次性的，必须走 `once`**。早先把升级对价并进了 `per_use`，
   等于每买一个末影珍珠都重新养一遍村民（`cleric/3` 的 160 腐肉被乘了 N 次）。
   现在升级产出一个独立的 `capability:villager:<职业>/<级>`，交易动作只挂 `once` 引用。
2. **每级每条报价各造一条 `train:` 动作**，产出同一个能力，由引擎比价。
   构建时拍一条会错：牧师 3 级既有「4 绿宝石买萤石」也有「2 兔子脚换绿宝石」，
   只有 20 TU 量级的差别，但选错了整条路线会贵一倍。
3. **卖货换绿宝石必须建模**。`gives` 是绿宝石的报价在升级开销里记**负**需求，
   卖出去换来的绿宝石正好抵扣。不建的话升级只能走「花绿宝石」那条，
   绿宝石需求全部靠箱子路线，会把难度推高。

实测牧师 4 级：1→2 用「1 绿宝石买红石」（xp=1，10 次）、2→3 用「买青金石」
（xp=5，12 次）、3→4 用「买萤石」（xp=10，8 次），能力总成本 **43.43 TU**，
加购买价 5 个绿宝石 = 50.11。末影珍珠最优仍是猪灵交易 **18.40**。

传导：藏宝图靠制图师交易，所以 `amethyst_shard` 69.70 → **133.33**；
`diamond` 不变（用的是 1 级图）。

### 刷怪模型的两条口径

`mob_spawn` 给的是**静态规则**，不是实测密度，三处用途要分清：

| 用途 | 取法 | 为何 |
|---|---|---|
| 结构里刷 | `w / W`（同 `category` 内）是「刷出来的就是它」的机率 | 平均打死 `W / w` 只才出一只；`monument` 的守卫者占比 100%，`fortress` 的凋灵骷髅 8/28 |
| 袭击 | `count_min/max` = 整场总量，`wave` = 波数 | 事件不是随机刷，产出固定，按「一趟打完」计价 |
| 群系自然刷 | 同 `w / W`，`W` 取同 `category` 总和；「等一只」周期拍 5 秒 | 只在结构/袭击都不出活时才用，全仓唯一无数据支撑的时间常量 |
| 密度 | 仍用 `mob_density`，不用 `mob_spawn` | 刷怪权重乘不了时间，算不出「每小时几只」 |

`biome:*` 那 811 条走最后一行：不猜「停留时间」，改用权重占比推
「平均打死几只才出一只想要的」，再乘 `等一只 + 打死一只`。
`ghast_tear` `inf` → **29.80**，全表 `inf` 清零。
等待周期 `NATURAL_SPAWN_SECONDS = 5.0` 是全仓唯一纯拍的常量，
所以优先级排在结构/袭击之后（推导见 gap-register 的 H1）。
