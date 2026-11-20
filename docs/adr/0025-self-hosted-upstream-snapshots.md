# 上游数据改为「自持快照」组织，不再依赖 ref 工作目录

> **后续修订**：`data/vanilla` 与 `data/packs` 已并入上游同步，当前入库的只有 `data/knowledge/`；`data/stats/` 与 `data/upstream/` 一样可由命令重建，不入库。

## 背景

本项目要用到三类外部数据，全部位于兄弟目录的两个上游项目里：RecipeAnalysis（可达性图与事实表）、WorldGenStatsCollector（世界统计）。过去的方式是给 `ref/` 建 junction 指向这两个项目的工作目录，代码里散落硬编码相对路径。

这个方式有三个问题，且互相放大：

1. **重复就不该发生。** 两个上游项目各自从同一个 `server.jar` 里挖原版数据——同一份 `loot_table`（1447 个文件 / 1.01 MB）在 `RecipeAnalysis/inputs/26.3/data/` 和 WGS 的 `.server/26.3/` 下各有一份，`server.jar` 本身（62,294,556 字节）在两个项目下各存一份，**逐字节相同**。本项目一份都不需要。
2. **依赖的是工作目录，不是发布物。** 上游改一次中间文件、清一次缓存、跑一次新统计，本项目的输入就悄悄变了。`data/stats/` 下曾同时留着多个时间戳目录，`_latest_run` 靠目录名排序猜哪个是「当前」。
3. **挂载面积极度失衡。** 实际需要的依赖只有 28 MB，但 `ref/` 树挂进来 1.5 GB+：

| 目录 | 体积 | 本项目是否需要 |
|---|---|---|
| `RecipeAnalysis/output/26.3` | 16.87 MB | 需要（图 + 事实表） |
| `RecipeAnalysis/inputs/26.3` | 170.8 MB | 只需其中 1.01 MB 的 `loot_table` |
| `RecipeAnalysis/ref` | 492.2 MB | 不需要 |
| `WGS/.server` | 892 MB | 只需其中 1.22 MB 的地形包 |
| `WGS/node_modules` | 26.6 MB | 不需要 |

其中 `WGS/.server/26.3/` 下 892 MB 里有 550 MB 是 `world/`、183 MB 是 `world_ori/`，而唯一需要的产物是 `world/datapacks/FASBingoWorldgen_*/` 里的 112 个文件——0.03 MB 的战利品覆盖埋在这 892 MB 里。

## 决策

**把依赖分成四类，只有前两类入库。**

| 类别 | 位置 | 性质 | 是否入库 | 体积 |
|---|---|---|---|---|
| 原版静态数据 | `data/vanilla/<pack>/` | MC 官方发布物，本项目的**输入** | 是 | 1.01 MB |
| 地形包 | `data/packs/<name>/` | 地形包原件，本项目的**输入** | 是 | 1.22 MB |
| 上游产物 | `data/upstream/<pack>/` | RA / WGS 的**产出** | 否，可重建 | 18.41 MB |
| 上游工作目录 | `ref/` | 别人的 junction | 否 | — |

划分依据是**能否重建**：原版数据与地形包只能从 jar 里挖，上游哪天不提供就得重新剥一次，必须自己留一份；RA 与 WGS 的产物有 `bg data sync` 一条命令就能重造，留快照只是为了离线可开发。

配套两个模块：

- `src/bingo_grading/paths.py` 是所有外部路径的唯一出口。解析优先级 **显式参数 > `data/` 自持 > `ref/` 回退**，每次解析返回 `Resolved(path, layer)`，`layer ∈ {override, local, ref, missing}`。回退到 `ref/` 不是静默的——`Resolved.local` 会是 `False`，`doctor` 的 `data-sources` 检查会报 FAIL。
- `src/bingo_grading/upstream.py` 执行同步与校验。`sync()` 按四类把数据复制进 `data/` 并写 `data/upstream/<pack>/manifest.json`（每条记录文件数、字节数、顺序无关的内容摘要、源路径、层）；`verify()` 重新计算摘要，不一致即报错。

## 后果

**同步实测：1633 个文件 / 20.63 MB**，是 1.5 GB 挂载面的 1/70。

**切断 `ref/` 后整条管线独立工作**（把 `paths.REF_ROOT` 指向不存在路径，7 条命令全部返回 0）：`doctor`、`bg data ingest`、`bg data loot`、`bg index sources`、`bg index slots`、`mining`、`bg plan`。`doctor` 的 `data-sources` 报告 `fully_local = True`。

**代价**：`data/upstream/` 需要在克隆后跑一次 `bg data sync`，否则 `doctor` 会对 `recipe-analysis` / `collector_run` 报 missing（若上游 junction 还在，则退化为 `ref` 层，仍可跑但被标记）。这是有意的——宁可显式失败，也不要悄悄用上不知道哪个版本的产物。

**顺带修掉的隐患**：`doctor` 的 `--pack` 默认值原本是 `fixture-2026.11`（虚构占位数据），导致默认诊断永远在检查假数据而不是 `data/stats/26.3/` 的实测结果。改为 `26.3`。

## 地形包是增量补丁，不是完整数据源

最初把地形包当成「一套完整数据」对待，是错的。实际情况有三层：

**一、它只覆盖自己关心的文件。** 地形包（当前 `FASBingoWorldgen_26.1_2.2.0`）的 115 个文件里，战利品表只有 2 张（`enderman`、`piglin_bartering`）。其余 1447 张表全部来自原版。所以加载必须是「原版打底 + 地形包覆盖」，`loot.tables.load` 的整文件替换语义正好对应数据包行为。

**二、包内还按数据包格式号分层。** 子目录 `26_2_overworld`、`26_3_loot` 之类不是「版本命名习惯」，而是 `pack.mcmeta` 里声明的 overlay：

| overlay | 生效格式区间 | 26.3（data 121.0） |
|---|---|---|
| `26_2_overworld` / `26_2_nether` / `26_2_loot` | [104,0] ~ [107,1] | 全部跳过 |
| `26_3_overworld` / `26_3_nether` | [118,0] ~ [121,0] | 启用 |
| `26_3_loot` | **[119,0] ~ [121,0]** | 启用 |

格式号取自原版 `version.json` 的 `pack_version.data_major/minor`（26.3 是 `121.0`）。三份同名 `enderman.json`（base 888 B / 26_2 832 B / 26_3 819 B）内容各不相同，取错版本就直接用错数值。

**三、`26_3_loot` 的下界比同前缀的另外两层高一级（119 vs 118）。** 这意味着在格式号 118 上，overworld/nether overlay 启用而 loot overlay 不启用——「按目录名前缀猜版本」在这个边界上必然出错。

因此新增 `src/bingo_grading/packs.py` 解析 `pack.mcmeta`，把「该启用哪些层」变成区间判定的结果，而不是字符串匹配。`paths.vanilla_version()` 提供格式号来源（从 `server.jar` 抽出 `version.json` 自持，几百字节，不必留 62 MB 的 jar）。

> 后续修订：`packs.py`、`paths.vanilla_version()`、`version.json` 同步均已移除——overlay 判定改由 RecipeAnalysis 完成，见 [ADR 0029](0029-datapack-merge-owned-upstream.md)。

### 这一轮修掉的三处实质问题

1. **同步漏掉 `pack.mcmeta`。** 地形包同步按 `kinds=(".json",)` 过滤，而 `pack.mcmeta` 的后缀是 `.mcmeta`——正是判定启用层的唯一依据被丢掉了。改为地形包不过滤后缀（LICENSE / README 一并不足 1 KB）。
2. **层序颠倒。** `_pack_loot_dirs` 把主包 `data/` 放在返回列表**最后**，而 `load()` 是「后加载覆盖先加载」——结果基础的 `enderman.json` 盖掉了 26.3 版本专用的那份。改为主包在最前。
3. **worldgen 文件被当成战利品表。** `_namespace_roots` 的兜底分支把「有 `data/` 但没有 `loot_table/`」的目录整体 rglob 成表，于是只覆盖 worldgen 的 `26_3_overworld` 贡献了 41 个假表。改为这种情况直接返回空。修后 `tables_loaded` 从 1489 回到 1447（= 原版表数）。

### 数值影响：零

诚实地说，前两条修正**没有改变任何产出数值**：`enderman` 与 `piglin_bartering` 是 entity / gameplay 表，不进 `bg data loot` 的 chest 表报告，所以 `bg data loot` 的输出哈希前后完全一致。红石（3.0492 / 3.5862 TU）与金锭（2.179 / 17.96 / 23.0435 TU）的 DAG 结果也不变。

修的是正确性：现在「该读哪一层」有依据、可复核；将来一旦有物品依赖这两张表（末影珍珠、以物易物路线），拿到的会是 26.3 的值而不是基础层的值。

## 验证

- `tests/test_paths_upstream.py`：17 条。覆盖四层优先级（local 优先于 ref、override 优先于 local）、`Resolved.local` 语义、`collector_run` 多 run 取最新、地形包本地/回退两条路径、`summary().fully_local` 的正反两例；摘要的顺序无关性与空目录无关性、后缀过滤复制、`verify()` 检出篡改与缺 manifest；以及「同步取源只认上游层」（本地已有快照不会被当成源）与「`--dry-run` 数字等于实跑数字」。
- `tests/test_packs.py`：13 条。覆盖 overlay 区间闭区间判定、缺端点视为不限、格式号标量/二元组归一化、`active_overlays` 在 118 / 121 两个边界上的差异、`layer_dirs` 的主包优先顺序与「声明了但目录不存在」的跳过，以及增量补丁的两条语义：地形包只覆盖自己的表（其余回落原版）、只含 worldgen 的层不贡献任何战利品表。
- `tools/refcut_check.py`：把两项上游路径指向不存在的位置后跑完整命令集，输出 `build/refcut.txt`。这个脚本不进自动化测试，因为要跑全管线；它是发布前的验收动作。
- `tools/check_overlays.py`：打印实际的 overlay 判定与层序，`build/overlay-check.txt` 留档。
- 全量 `pytest`：246 通过。

## 修订：`ref/` 概念移除（后于本决策）

当时的做法是在仓库内建 `ref/`（junction）指向两个上游项目，再由配置层描述它。实际使用中 `ref/` 这层抽象没有带来任何好处：它只是两个固定路径的又一层转述。现在简化为：

- `config.yml` 直接给出两个上游项目的根：`paths.recipe_analysis` 与 `paths.collector`；
- 本仓库自有目录（`data/`、`build/`、`data/{stats,knowledge,schema}` 等）固定在 `src/bingo_grading/paths.py` 常量区，**不参与配置**；
- `paths.REF_ROOT` 已删除；`paths.REF_RECIPE_ANALYSIS` / `paths.REF_COLLECTOR` 保留（`__getattr__` 懒加载），语义从「`ref/` 下的子目录」变成「配置文件给出的项目根」。

本文其余部分的四层命名（`override` / `local` / `ref` / `missing`）仍然有效——`ref` 现在读作「上游项目」而不是「仓库内的 `ref/` 目录」。

### 配置格式：用真 YAML，加一条依赖

中途试过「不引入 PyYAML、自写一个极小的 YAML 子集」省掉依赖。这条路放弃了：文件叫 `config.yml`，`.yml` 后缀就是对 YAML 的承诺，自写方言会让维护者按 YAML 的直觉写（值里的 `#`、引号、列表），而解析器要么静默读错、要么拒绝在标准 YAML 里合法的写法。**静默读错比缺依赖贵得多。**

所以 `dependencies` 里多了 `pyyaml>=6`。代价里唯一需要处理的是隐式类型推断（`26.3`→float、`on`/`yes`→bool、`1:20`→60）：`config._PathLoader` 清空 `yaml_implicit_resolvers`，所有标量一律按字符串读，配置里没有一个值需要推断。模板里给路径加单引号只是**示教**，不是正确性的前提（YAML 单引号不做转义，Windows 反斜杠可裸写；双引号会把 `\g` 当非法转义）。

### 数据目录去噪：假快照、旧 run、旧包

三件事同源——都是「下游只该有一份当前数据」，多余的都是判断错误的入口：

- **`data/stats/fixture-2026.11/` 已删除。** 它是一份会被误当实测结果的假快照，而依赖它的只有解析器测试。改为 `tests/fixture_stats.py` 在 `tmp_path` 现造四层占位数据，仓库里不再有假数据。`bg stat` 的 `--pack` 默认值同步从 `fixture-2026.11` 改为 `26.3`。
- **`data/upstream/<pack>/worldgen-stats/` 只保留最新一次 run。** `collector_run()` 与 `cli._latest_run()` 都是 `sorted(...)[-1]`，历史 run 永远读不到，且不在 manifest 内、`bg data verify` 也管不到。同步时应当先清旧 run 再复制。
- **旧版地形包副本已删除。** 地形包从 `2.1.0-lava-lakes` 换到 `2.2.0` 时，`data/packs/` 里留了旧副本，而 5 个审计脚本（`check_loot_layers` / `check_loot_parity` / `check_overlays` / `compare_pack_layers` / `probe_pack_format`）把旧包名写死在代码里 —— 他们一直分析上一版地形而不报错。两版的实际差异不小（`lake_lava_surface` 的 `rarity_filter.chance` 25→100、`pillager_outposts` 的 `exclusion_zone.chunk_count` 10→4）。

地形包的原件与 `data/packs/` 这一层后来整个移除了：overlay 判定与逐层覆盖改由 RecipeAnalysis 统一完成，见 [ADR 0029](0029-datapack-merge-owned-upstream.md)。
