# 0029 数据包合并归上游，本侧只消费合并结果

地形包（datapack）是原版地形的**增量补丁**：它只覆盖自己关心的少数文件，其余沿用原版；包内还按 `pack.mcmeta` 声明的格式区间分层（overlay），哪一层生效由原版格式号决定，不是目录名。

## 问题

「原版打底 + 挑出适用的 overlay + 逐层整文件覆盖」这套语义，最初由本项目自己实现（`packs.py` 读 `pack.mcmeta` 判区间、`cli._pack_loot_dirs` 选层、`loot.tables.load` 按表 id 覆盖），并同步一份地形包原件到 `data/packs/`。

而 RecipeAnalysis 也在读同一批数据包——它导出的 `facts/loot_table.jsonl` 取自 `inputs/<pack>/data/`（原版解包），**没有应用地形包覆盖**。于是同一张表在两个项目里结论不同：

| 来源 | `minecraft:entities/enderman` 的 `set_count.count.min` |
|---|---|
| 本项目（自己合并） | `1`（地形包让末影珍珠必掉 1 个起） |
| RA `facts/loot_table.jsonl` | `0`（原版值），`prov.input: "src"` |

眼下不冲突，只因为 RA 只做存在性判断（0 或 1 都是「会掉」）。但只要 RA 要算任何数量，两边就会直接矛盾。两套实现必然分叉，只是时间问题。

## 决策

**overlay 判定与逐层覆盖归 RecipeAnalysis**，它在 `inputs/<pack>/datapack-merged/` 产出合并后的完整 `data/`（并写 `.datapack-merge.json` 与 `merge-log.jsonl` 记录每个包/overlay 的 `applicable` 判定与跳过原因）。本项目：

- `bg data sync` **整包**同步 `datapack-merged/data/` 到 `data/upstream/<pack>/datapack/data/`，并把上游合并包没导的 `minecraft/structure` 补进同一处；
- `bg data loot` 从 `datapack/data/minecraft/loot_table` 取表，不挑层、不叠加；
- 仓库不再保留地形包原件（`data/packs/`）与独立的原版目录（`data/vanilla/`）。

**同步不做文件级过滤**。最初实现过一版白名单/黑名单（跳过 `ledger.jsonl`、`paths_*.{dot,html,svg}` 之类），后来全部撤掉：过滤会把「上游本来有、但被我们排除了」和「上游真的没产出」混成同一个现象，排查时无从区分。整包代价很小——合并后的数据包全量 8405 文件也只有 6.1 MB——而漏数据的代价是错的结果。同理 `worldgen-stats/<run>` 也不再只取 `.json`（之前漏了 2 个非 json 文件）。

**只有一个数据包视图，没有 `vanilla`。** 早先分成 `data/vanilla/<pack>/`（原版）和 `data/upstream/<pack>/loot-tables/`（合并结果）两棵子树，是因为把「原版」当成了稳定概念。但地形包原则上可以覆盖任何类别，只要它将来覆盖了 `structure`，「原版」这个标签就开始撒谎。现在统一成 `data/upstream/<pack>/datapack/data/`——一份「本项目实际消费的数据包」，`loot_table` 与 `structure` 并肩待在 `data/minecraft/` 下，谁来自合并包、谁来自 datagen 缓存是实现细节，不体现在目录名里。

`version.json` 与地形包原件一并停同步：格式号原用于本侧判 overlay，判定归上游后它就没有消费者了，`paths.vanilla_version()` 与 `_sync_version_json()` 一并删除。

另外，`paths.loot_tables()` 找不到合并产物时**不回退**到未合并的原版表，直接报 MISSING：静默用未合并的表会让地形包覆盖丢掉，算出来的期望值看起来正常但是错的。

分工按**语义归属**切分，不按「谁先实现」：

| 环节 | 归属 | 理由 |
|---|---|---|
| 读 `pack.mcmeta`、判 overlay 区间 | RA | 数据包语义 |
| 原版 ⊗ 覆盖层 按表 id 合并 | RA | 所有消费者都该看到同一份「生效后的表」 |
| 每箱期望、每结构箱数、触发口径 | 本项目 | 评分口径，RA 不做 |

## 迁移验证

- 迁移前后各重建一次 `loot_expectation`：行数 1641 → 1641，主键集合完全一致，`value` / `sample_size` / `confidence` **零差异**；只有 `provenance` 从 `loot:loot_table+<pack>+26_3_loot` 变为 `loot:loot_table`（不再有叠加层）。
- 用 `mcshared` 分别加载「RA 合并结果」与「原版 + 地形包层」，1447 张表里只有 `enderman`、`piglin_bartering` 两张不同——正是被覆盖的两张。逐字段比对后确认是**形态差**而非语义差：RA 输出用 `functions` 键（已归一方言）而包文件用 `modifier`；RA 显式写 `bonus_rolls: 0.0` 而包文件缺该键（归一为 `None`）。`bonus_rolls` 全项目没有任何消费方，不影响计算。

## 代价

- **失去双轨交叉验证**：此前两份独立实现可以互相校验，现在只信 RA，它的合并 bug 本侧无从发现。缓解方式是把上面那套逐表比对固化成一次性验收工具，在切换或升级上游时跑一次。
- RA 的 `datapack-merged/` 目前位于 `inputs/`（解包产物区），而不是 `output/`（产物区）；它的生命周期与 `ra inputs init` 绑定，语义上略偏。

## 一并移除

`packs.py`、`cli._pack_loot_dirs` / `_has_loot_tables`、`paths.terrain_pack` / `paths.upstream_terrain_pack`、`upstream.current_terrain_packs` / `_terrain_pack_names`、`bg data loot --pack`、`data/packs/`、`tests/test_packs.py`，以及 5 个审计工具中的 3 个（`check_loot_layers` / `check_overlays` / `compare_pack_layers`，它们的工作现在由 RA 的 `merge-log.jsonl` 承担）。
