# 世界统计采集侧：改造与新增工作单

本文是给 `WorldGenStatsCollector` 的工作单，由下游评分项目（BingoItemGrading）按自己的数据需求反推而来。

> 本文放在下游仓库里维护，因为它是**下游对上游的需求契约**。需要在上游仓库跟踪时，整份复制到上游的 `plan/` 下，不要拆成两处各自演进。

## 0. 结论摘要

**C1–C7 已在 `2026-11-06T15-16-14-191Z` 这次运行中全部落地**，本文保留作契约记录与剩余项跟踪。

| # | 问题 | 影响 | 状态 |
|---|---|---|---|
| C1 | 产物不含 Minecraft 版本、种子、地形包身份 | 下游无法证明这批统计来自该地形包，也无法复算 | ✅ 已实现 |
| C2 | `level-seed` 为空，每次 setup 随机 | 稀有结构（府邸只测到 1 个）的观测不可复现 | ✅ 已实现（`seedMode: random` 并落盘实际种子） |
| C3 | `result` 不分维度 | 一旦跑下界/末地，各维度数字会合并在同一个对象里 | ✅ 已实现（`result` 按维度嵌套） |
| C4 | `area` 是人读字符串，不是结构化对象 | 下游只能正则解析，边界一改就断 | ✅ 已实现（`range` + `rangeByDimension`） |
| C5 | 单位只写在 `note` 散文里 | `meanNNChunks` / `per_chunk` / `per_section` 混淆风险 | ✅ 已实现（`units` 对象） |
| C6 | 缺 `biome_patch` 分析器 | 群系「多大一坨」无法计算 | ✅ 已实现（`biome-patch`） |
| C7 | `ore-exposure` 没有群系轴 | 恶地金矿、山地绿宝石的富集完全看不出来 | ✅ 已实现（改用独立分析器 `biome-ore`） |
| C8 | 只预生成主世界 | 下界 3 种矿石、下界/末地结构无数据 | ✅ 已实现（`2026-11-11T16-05-19-027Z`：三维度都有 `ore-stats.<dim>.json` 与 `structure-interior.<dim>.json`） |
| C9 | 稀有群系样本不足（`reliable: false`） | 恶地仅 20–38 区块，富集数值不可用 | ⬜ 未实现（下游已按方块数自行判定可用性，见 [ADR 0019](../adr/0019-density-sample-size-in-blocks.md)，故此项不再是阻塞） |
| C10 | 矿石密度没有纵段分解 | 无法区分「浅层可挖」与「深层要掘」，恶地金矿正卡在这里 | ✅ 已实现（群系级带 `sectionProfiles` 纵段剖面） |
| C11 | 无地下空洞率/通道密度 | 「最多去矿洞」这条路径无法量化 | ⬜ 未实现 |
| C12 | 结构间距只有全域值 | 分不出「从目标群系内出发」与「从群系外出发」 | ⬜ 未实现 |
| C13 | 非矿石方块无群系级密度 | `chorus_plant`、原木、沙、陶瓦都算不了 | ✅ 已实现（`section-block-histogram` → `block_density`，518 行） |
| C14 | 非矿石方块无暴露率 | 只能按方块名后缀猜「地表/地下」，`bamboo` 被算成 64 TU（实际长在地表，差 62 倍） | ✅ 已实现（`cave-exposure` → `block_exposure`，6 面判定且把天空/洞穴拆开） |
| C15 | 地牢未按高度拆分 | `structure-interior.dungeons` 只有 `count` / `byKind`（僵尸/蜘蛛/骷髅），没有深度轴；下游算搜索成本时分子只能取浅层洞穴、分母却是深浅之和 | ✅ 已实现（`dungeons.byDepth`：shallow 2603 / deep 4954，各带 `containers` 与 `containersPerDungeon`；下游已导入为 `by_depth`） |
| C16 | `structure_content.containers_per_start` 覆盖只有 13/53 | 40 个结构变体算不出「一趟能开几个箱」，它们的箱子来源只能整条缺席 | ✅ **已解决**：`2026-11-11T16-05-19-027Z` 的 `structure-interior` 按结构给出 `containers` / `containersPerStart` / `containersPerCoveredChunk`，下游覆盖升到 **54/58**。仅剩 4 个变体无箱数，其中 `monument` / `nether_fossil` / `swamp_hut` 在 vanilla 里本就没有战利品箱，不是缺口；`pillager_outpost` 的问题是缺结构集合级密度（C12 范畴） |
| C17 | ~~敌对生物没有 `mob_density`~~ | 敌对生物密度依赖玩家活动（mob cap、光照、距离），**静态扫描给不出可信值** | ❌ **已撤回**，不作为上游需求。下游不再按「刷怪密度」估怪物掉落，改按结构/生物群系可遇见性 + 掉落期望处理 |
| C18 | ~~结构内方块与下界方块没有 `block_density`~~ | `iron_block` / `redstone_wire` / `nether_gold_ore` / `gilded_blackstone` 只在结构里放置 | ✅ **已解决**：C16 的 `structure-interior` 顺带给了 `blocksPerStart`，下游据此反查「哪个结构放它、每处几个」 |
| C19 | 结构**渲染规则**产生的生物没有统计 | 唤魔者、守卫者、凋灵骷髅、恶魂这类生物由结构生成规则持续产生，玩家不在场时不存在——静态扫描看不到，`entity-census` 也只统计陆生/水生动物 | ✅ **已解决**：RA 的 `spawn_tables.jsonl`（887 行）→ 下游 `mob_spawn`（850 行），结构权重与袭击波次都已接进动作图 |
| C20 | 交易报价的 `xp` / `max_uses` 只覆盖 68% / 96% | `facts/trade.jsonl` 391 条 `offer`：266 条带 `meta.xp`、374 条带 `meta.max_uses`。缺的 125 条 = **100 条流浪商人**（无等级，`status: partial` 是对的）+ **22 条 1 级买货** + 2 条其它 + 1 条 3 级 | ✅ **已在下游解决，不需上游改**。vanilla 的 `villager_trade/*.json` **省略**这两个字段时由 codec 给默认值（`max_uses=4`、`xp=1`），RA「只透传文档里真有的键」是对的。下游在 `importers/trade.py` 按 codec 默认值补全（`DEFAULT_MAX_USES` / `DEFAULT_XP`） |

**已撤回的两项需求**见第 4 节：战利品期望与刷怪数据都不该由本项目采集。

**验证结果**（基于 `2026-11-06T15-16-14-191Z`）：

- `target.dataPacks[0].sha256 = f44ef3f9…`、`seed = 439625976969540166`、`seedMode: random`。
- `biome-ore` 修复了假零：恶地金矿 `26.56/区块`（此前维度级为 3.86 且无法归因），山地绿宝石 `1.74/区块`。**但两者都是 `reliable: false`**——恶地只 38 个区块、山地 181 个，不足以定住数值。可靠群系内矿石密度极差仅 1.3–1.5 倍，详见 C9。

  > 后续修正：`reliable` 的判据是区块数，衡量空间覆盖；密度估计的误差实际由数到的方块数主导。恶地金矿有 483 块样本，密度估得住。下游已改按 `total_blocks` 判定可用性（[ADR 0019](../adr/0019-density-sample-size-in-blocks.md)），C9 因此不再阻塞矿脉类计算；但仍影响「该群系平均富集度到底差多少倍」的精细标定。
- `biome-patch` 给出 55 个群系的斑块规模、地表开放性与邻接关系。
- 下游导入行数从 54 增至 **1034**；`block_drop` 覆盖率从 15/19 升至 **19/19**。

---

## 1. 契约缺口（P0，必须先改）

这三项不改，下游拿到的数字无法证明「来自这个地形包」，也无法在换包后判断该不该信任。

### C1 产物头部补标识

每个分析器文件与 `summary.json` 的顶层都加：

```json
"target": {
  "minecraftVersion": "26.3",
  "levelName": "world",
  "loader": "fabric",
  "seed": "1234567890",
  "seedMode": "explicit",
  "dataPacks": [
    { "id": "FASBingoWorldgen_26.1_2.1.0-lava-lakes", "source": "world", "sha256": "…", "enabled": true }
  ],
  "serverJarSha256": "…"
}
```

- `seedMode`：`explicit`（配置里给了）/ `random`（服务端随机，此时 `seed` 记实际生成的种子）。
- `dataPacks`：扫描 `world/datapacks/` 与 `datapacks/`，给每个包算内容哈希（目录树逐文件哈希后汇总，不要只哈希目录名）。

已核实：`world/datapacks/FASBingoWorldgen_26.1_2.1.0-lava-lakes` 确实存在，但身份没有落进任何产物。这是下游 `world_stat.pack_version` 的唯一凭据，缺了只能记 `unknown`。

### C2 种子必须落盘且可指定

`server.properties` 的 `level-seed=` 当前为空 → 每次 `setup` 生成不同的世界。

- 配置项 `server.seed` 为空时，`setup` 生成一个随机种子**并写回 `server.properties`**，同时记进 C1 的 `target.seed`。
- 下游只要求「可复现」，不要求固定值。林地府邸、丛林神庙、沼泽小屋各只测到 1 个起点，这类观测必须能重跑验证。

### C3 `result` 按维度分层

现在 `dimensions: ["overworld"]` 是扁平列表，`result` 也是扁平对象。跑两个维度时，两边的 `byOre`、`byType` 会落进同一个键。

改为：

```json
"result": {
  "minecraft:overworld": { "chunks": 19044, "byOre": { … } },
  "minecraft:the_nether": { "chunks": 11025, "byOre": { … } }
}
```

维度 ID 用命名空间形式（`minecraft:overworld` / `minecraft:the_nether` / `minecraft:the_end`），不用 `overworld` / `DIM-1` 两套写法。

**要求直接切成新形态并升 `schemaVersion`，不要为兼容旧形态加分支。** 下游只有一个消费者，改一次比长期维护两种形状便宜。

---
