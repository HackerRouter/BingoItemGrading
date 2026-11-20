# 统计层

一条统计是七元主键加一组分量值。本文规定形状、回退语义与导入口径，实现见 `src/bingo_grading/stats/`。

## 主键

```
(pack_version, scope_level, dimension, biome, stat_type, subject, condition)
```

不适用的分层字段填空串，不用 `null`：空串让主键可以直接用元组比较。

| `scope_level` | `dimension` | `biome` | `subject` |
|---|---|---|---|
| `global` | 空 | 空 | 可空 |
| `dimension` | 必填 | 空 | 可空 |
| `biome` | 必填 | 必填 | 可空 |
| `biome_subject` | 必填 | 必填 | 必填 |

`condition` 是自由字符串（如 `layer=underground`），参与主键与回退匹配。

`subject` 是**测量对象**，不一定等于来源的 `subject`。两套标识的关系见 [ADR 0011](adr/0011-measurement-identity-vs-source-identity.md)。

## 值结构

`stat_type` 分两类：`SPATIAL_TYPES` 是可回退的空间测量，按维度与群系查；`FACT_TYPES` 是按名字精确连接的命名事实，没有回退语义。`resolver` 只服务前者。

`value` 按 `stat_type` 有固定键集合：`required` 缺一即错，`optional` 可缺省，多出键也报错。

| `stat_type` | 必需键 | 主要可选键 |
|---|---|---|
| `ore_density` | `per_chunk_density` | `equivalent_chunks` `chunks` `total_blocks` `reliable` `by_section` |
| `block_density` | `per_chunk_density` | 同上（非矿石方块，上游 `bulk` 类） |
| `ore_exposure` | `air_exposed` `water_exposed` `buried` `per_chunk_density` `air_exposed_share` | `by_section` `family` |
| `block_exposure` | `per_chunk_density` `sky_air_share` `cave_air_share` `water_share` `buried_share` | `air_exposed_share` `cave_share_of_air` `both_air_share` `unknown_share` `sample_blocks` `reliable` |
| `section_fill` | `sections` | `chunks` |
| `structure_density` | `expected_nearest_distance` | `spacing` `separation` `biome_conditions` `structure_set` `structure_ids` `observations` `median_nearest_distance` `mean_size` `density_per_1000_chunks` |
| `mob_density` | `per_chunk` | `chunks_per` `groups_per_chunk` `avg_group_size` `avg_y` `category` |
| `spawn_distribution` | `biome_weights` | `underground_biome_weights` `water_share` |
| `biome_patch` | `patch_density` `mean_area` `area_variance` `area_fraction` `vertical_condition_prob` | `patches` `median_area` `max_area` `edge_touch` `neighbors` `autocorr_tier` `reliable` |
| `loot_expectation` | `per_trigger_expected` `trigger` | `table` `chests_per_structure` `structure_frequency` `assumptions` `unsupported` |
| `structure_content` | `source` `containers` `loot_tables` | `templates` `containers_per_start` `loot_tables_per_start` `blocks` `blocks_per_start` `spawners_per_start` `entities_per_start` `by_depth` |
| `trade_offer` | `offers` `offer_count` | `trades_ref` |
| `mob_spawn` | `holder` `holder_kind` | `weight` `count_min` `count_max` `category` `requires` `wave` `wave_counts` |

空间测量类额外允许 `variant_breakdown` 与 `between_variant_variance`，变体细分留到诊断报警后再填。

`structure_density` 只强制要求 `expected_nearest_distance`：间距与间隔是它的上游输入，测量样本不足时才由间距推导，推导行 `derived_from` 记 `configured.spacingChunks`、`confidence` 降为 `low`。它同时承载「离散散布特征」——地表岩浆湖按此类型导入，`structure_set` 填 `minecraft:surface_lava_lake`。

`biome_patch.vertical_condition_prob` 的含义固定为**该群系真正开放、可走过去的地表比例**（地表方块上方为空气且非水）。它不是「资源在垂直方向的出现概率」——后者由 `ore_density` 按群系给出。

`section_fill` 是**逐纵段的实心占比**（维度级，每维度一行）：`fill = avgTotal / 4096`，`fill_dry` 再把水与岩浆扣掉。它描迳的是**段**而不是方块，所以能脱离具体方块查询——下游要看的正是「某方块主段的**上面那一段**敞开不敞开」（见 [`units.md`](units.md)）。

两个计数陷阱：

- **`avgTotal` 包含水**。海底沙所在段 40.5% 是水、实心占比 96.2%，不扣水就会把水下露头误判成埋着。
- **不能看本段，要看上方段**。海底沙本段扣完水仍 55.7%（段的下半部分是海床下方的实心），而它上方 y64 段只有 27.7%——后者才是「抬头看得到天空」的判据。

取**主段**（数量最多的段）而不是最高段：最高段常常只占总量的 0.0%。

它只是**代理**：地下大洞穴所在的段按 16 格平均后填充率依然很高（繁茂洞穴段 89.1%），所以「方块自身是否暴露在洞穴空气中」它给不了——精确口径是 `ore_exposure.air_exposed_share`（含 cave 空气，见采集侧需求 C14）。

`biome_patch.area_variance` 用**变异系数平方**（`var / mean²`），不是原始方差：原始方差随尺度变，跨群系不可比。`area_variance` 是最弱的可靠性信号，`edge_touch > 0` 表示有斑块被扫描边界截断，此时 `mean_area` 会系统性偏低。

`ore_density` 与 `ore_exposure` 是两个口径，不能互换（[ADR 0012](adr/0012-biome-ore-density-without-exposure.md)）：

| 类型 | 层级 | 分母 | 含暴露 | 用途 |
|---|---|---|---|---|
| `ore_density` | 群系 | 该群系等效区块数（地表列数/256） | 否 | 专程进群系挖矿道 |
| `ore_exposure` | 维度 | 扫描区块总数 | 是 | 顺路捡 |

两者分工对应槽位的 `obtain_method`：`mine` / `branch_mine` 查 `ore_density`，`surface` 顺路获取查 `ore_exposure`。

**不需要矿簇密度**（[ADR 0015](adr/0015-ore-block-density-not-vein-density.md)）：挖掘代价与矿道长度成正比，期望收获 = 体积密度 × 扫过体积，这个式子与矿石是否聚簇无关（簇的碰撞截面更大但簇数更少，两者抵消）。矿簇只影响方差，不影响期望；而 Bingo 一个格子通常只要 1 个物品，单块掉落已在掉落表里。

直接可用于 P3 的派生量（矿道截面 `S`、体积密度 `ρ`）：

```
期望收获 = ρ · S · L          （走过 L 格的期望块数）
撞 1 块格数 = 1 / (ρ · S)
```

以主世界实测（截面 1×2）：`deepslate_redstone_ore` 在 y[-64,-49] 约 **135 格**撞 1 块；`iron_ore` 在 y[16,31] 约 106 格；`deepslate_diamond_ore` 在 y[-64,-49] 约 283 格。

单位容易弄错：是 `1/(ρ·S)`，不是 `S/ρ`。前者单位是「格」，后者是「平方格/方块³」，量纲就不对。

这个换算要求 **群系 × 纵段** 的密度。当前主世界 `biome-ore` 只有整柱平均（下界版已有 `sectionProfiles`），所以群系级的「挖多深」尚不能算，属 C10。

统计类型没有对外依赖：`loot_expectation` 由本侧解析战利品表算出，采集侧不做表解析；其余类型由采集侧产物导入。

## 回退

查询按 `biome_subject → biome → dimension → global` 查找，命中即返回：

- 回退只降 `scope_level`，`subject` 与 `condition` 不变。
- `fallback_level` 是**命中层的绝对层号**（`SCOPE_ORDER` 下标）：0 = `biome_subject`，1 = `biome`，2 = `dimension`，3 = `global`。它不是「候选序号」——同一层命中会因查询带不带 `subject` 而给出不同数值（`ore_density` 只有群系层、`biome_patch` 天然无 `subject`，两者必须都记 1）。
- 完全缺失时 `fallback_level` 记为 `none`。
- 完全缺失返回 `value = null`，不编零值。零值会让下游算出「代价为零」的免费物品。
- 不同类型不互相回退：`ore_density` 缺失时不得拿 `ore_exposure` 顶替（两者分母与口径不同）。

当前采集侧只产出群系级（`ore_density`、`biome_patch`）与维度级（其余）统计。带 `biome` 的 `ore_exposure` 查询会回退到维度层（`fallback_level = 2`）；`ore_density` 若某群系无行，查询直接缺失，不会降到维度层——这是设计，不是缺陷。

## 其他字段

| 字段 | 含义 |
|---|---|
| `sample_size` | 采样量（区块数或结构起点数） |
| `confidence` | `high` / `medium` / `low`，按采样量分级，阈值见 `confidence_for()` |
| `parent_scope` | 回退链上一层的七元主键，用于一致性检查；解析不依赖它 |
| `derived_from` | 该值由哪些原始字段派生 |
| `provenance` | 来源文件，形如 `<运行目录>/ore-exposure.json` |
| `synthetic` | 是否为虚构占位数据 |
| `note` | 该行口径的说明，含已知局限 |

## 导入

`bg data ingest` 读世界统计收集侧的一次运行目录，产出：

- `data/stats/<pack_version>/spatial.jsonl`：可回退的空间测量（9 类，按 `scope_level` 分层）。
- `data/stats/<pack_version>/facts.jsonl`：命名事实（4 类：结构内容、战利品期望、交易报价、刷怪规则）。
- `data/stats/<pack_version>/meta.json`：布局版本、地形包版本与去重后的 `note` / `derived_from` / `provenance` 表（行内只存下标 `m`）。
- `data/stats/<pack_version>/target.json`：溯源——Minecraft 版本、种子与 `seedMode`、地形包 ID 与内容哈希、`serverJarSha256`、扫描范围。这是「这批统计属于哪个地形包」的唯一凭据。

只接受采集侧 `schemaVersion: 2`（`result` 按维度嵌套、按维度分文件）。v1 的扁平 `result` 已丢维度信息，遇到直接报错要求重跑，不做双形态兼容。

默认导入产物里出现的**全部维度**（`--dimension` 可限定一个）。

| 分析器 | 落成 | 口径 |
|---|---|---|
| `ore-stats`（`biomes[].exposure`） | `ore_density`（群系级，按方块） | 每群系等效区块的平均数；**不含暴露**（[ADR 0012](adr/0012-biome-ore-density-without-exposure.md)）；带 `by_section` 纵段 |
| `ore-stats`（`biomes[].exposure`） | `ore_exposure`（群系级） | 暴露分解；`air_exposed_share` 由 `airPct` 折算 |
| `ore-stats`（`biomes[].bulk`） | `block_density`（群系级） | 非矿石方块（紫颂植物、黑曜石、原木），上游只数数量 |
| `cave-exposure` | `block_exposure`（维度级） | **6 面邻接判定**：天空空气 / 洞穴空气 / 水 / 埋着 四分。与 `ore_exposure` 的区别是把天空与洞穴拆开了（后者混在一起，见 [ADR 0014](adr/0014-air-exposure-cave-conflation.md)） |
| `section-block-histogram` | `section_fill`（维度级） | 逐纵段实心占比：`fill = avgTotal/4096`，`fill_dry` 扣掉水与岩浆。用来判断「某位置上下是否敞开」 |
| `biome-patch` | `biome_patch`（群系级） | 斑块连通分量面积分布、地表开放性、邻接群系；`vertical_condition_prob` 取 `openSurfaceShare` |
| `biome-histogram` | `spawn_distribution`（维度级） | 权重是**地表面积占比**，作为出生分布的代理，不是出生点实测 |
| `structure-spacing` | `structure_density`（维度级，按结构集合） | 优先用实测最近距离；样本不足时由配置间距推导 |
| `entity-census` | `mob_density`（维度级，按基础实体） | 世界生成放置的实体实测；分母为扫描区块数；`null` 字段直接缺省 |
| `lava-lakes` | `structure_density`（`minecraft:surface_lava_lake`） | 只取地表；地下岩浆没有间距测量，不导入 |
| `section-block-histogram` | `block_density`（维度级，按方块） | 逐区段直方图汇总成「任意方块的每区块数量」，覆盖非矿石方块（粘土、干草块、原木等）。每区块不足 `0.01` 的方块不导入 |

`loot_expectation` **不由采集侧产生**，由本项目的 `bg data loot` 解析战利品表算出（[ADR 0017](adr/0017-loot-expectation-owned-downstream.md)），所以它不出现在采集侧的缺测清单里。

置信度：采集侧自带的 `reliable`（`chunks >= minChunks`）优先于本侧按采样量分级——前者衡量「该群系样本够不够」，后者只衡量「整体样本量大小」。`reliable: false` 一律降为 `low`。

**但 `low` 不等于不可用。** `reliable` 的判据是区块数，管的是**空间覆盖**；而密度是 `方块数 / 等效区块数`，其估计误差由数到的方块数主导。一个只覆盖 20 个区块却数到 289 块矿的群系（如疏林恶地的深层红石），密度估得住；反过来，覆盖 5000 个区块只数到 5 块的群系，区块再多也没意义。

因此下游判断「密度能不能用来算代价」时不看 `confidence`，而是直接看 `total_blocks`，阈值见 `gamedata.MIN_DENSITY_BLOCKS`（200，与上游 `minOreSamples` 默认值一致）。理由与取舍见 [ADR 0019](adr/0019-density-sample-size-in-blocks.md)。


导入不猜。以下情况一律进缺口报告，不写进 `world_stat`：

- 某维度在产物里不存在时，不写该维度的任何行，并在 `unmapped_provenance` 点名。
- 计数为 0 的方块不写 `ore_exposure` 行（零暴露会让「顺路能捡到」看起来成立）；`ore_density` / `block_density` 则保留真 0，因为那里表达「这个群系确实没有」。
- 结构没有任何距离测量，也没有配置间距。
- 没有对应 `stat_type` 的分析器（列在 `unmapped_analyzers`）。

## 战利品期望（本项目自算）

`bg data loot` 读战利品表目录与模板事实，产出 `loot_expectation` 行：

```
原版 data/  →  地形包 <minor>_loot/  →  地形包 data/
```

后者覆盖前者，整文件替换。两种主键粒度：

- `subject` = 表 ID（`minecraft:chests/simple_dungeon`）：单箱期望，最准。
- `subject` = 结构集合（`minecraft:villages`）：按箱数加权聚合，下游按它查。

`condition` 区分工具假设：`tools=present` / `tools=absent`。两行共存，因为工具直接改变结果（树叶带剪刀掉树叶，徒手掉树苗与木棍）。

`chests_per_structure` 取模板箱子数的中位数，`structure_frequency` 由 `structure_density.spacing` 换算（`1/spacing²`）。前者未模拟 jigsaw 拼装，属近似，`note` 已写明。

## 来源侧缺口

`bg data ingest --index <来源索引>` 额外比对两侧，口径分三层，避免「有映射的那部分全绿」盖住「大量来源压根没映射」：

- `required` / `covered` / `missing`：同一统计类型内，键在快照里缺行即缺口。
- `unmapped`：来源没有统计键（结构集合映射不到，`stat_subject` 为 `null`），按来源数与涉及物品数计。
- `no_stat_type`：该类来源第一版没有对应统计类型，不计入覆盖率。

`block_drop` 的检查对象是 `ore_density`（群系级），按「任意群系下有该矿石的行」判定，因为它本质上就是群系维度的量、不存在维度级版本。只有矿石方块需要它：木头、圆石这类方块来源的难度由群系覆盖与配方链给出。

分类型的统计键：

| 来源类别 | 统计类型 | 说明 |
|---|---|---|
| `block_drop` | `ore_exposure` | 只对矿石判定。非矿石方块（木头、圆石等 1400+ 条来源）第一版不查暴露密度，缺口报告单独计数，不算通过 |
| `mob_drop` / `shear` | `mob_density` | 按基础实体 ID |
| `loot_table` / `suspicious_block` | `structure_density` | 按结构集合；未映射的进 `unmapped` |
| `trade` | — | 无对应统计类型，交易代价由策略注册表给 |

## 失效

节点在计算前登记自己用到的查询；统计一改，`DependencyIndex.refresh()` 重新解析所有登记查询，命中行或行内容变化即把该节点标 dirty。

判定依据是「解析结果的指纹」而不是「改动行的主键前缀」：回退链让一条粗层统计同时是很多细层查询的后备，按前缀猜会漏掉这些查询。

## 快照

快照是 `data/stats/<pack_version>/` 下的三个文件（`meta.json` / `spatial.jsonl` / `facts.jsonl`），
一行一条，由脚本以 UTF-8 写出。空间测量与命名事实分开，是因为两者的查询方式不同：
前者按 `scope_level` 回退，后者按 `(stat_type, subject, condition)` 精确连接。
`note` / `derived_from` / `provenance` 在 `meta.json` 里去重存放，行内只存下标 `m`。
快照由 `bg data ingest` 生成，`pack_version` 是这次采集运行的输入标识，不是能力边界：
任何由采集侧跑出的地形包都会落到自己的 `<pack_version>/` 目录。
快照不入库，克隆后按 `bg data sync`、`bg data ingest`、`bg data loot` 重建。
需要多层级（global / dimension / biome / biome_subject）测试数据时，由
`tests/fixture_stats.py` 在临时目录现造，**不往 `data/` 里放假快照**。
