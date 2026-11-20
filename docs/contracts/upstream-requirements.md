# 上游数据需求

本文只列**本侧算不出来、必须由上游新增**的数据。凡能从现有产物算的，都算本侧的接线工作，
不写在这里。

已完成的历史需求已从本文移除（结构内部布局与模板分布、结构内实体与刷怪笼、交易报价对价、
`exploration_map` 产物 ID、graph 语义那三类、`code/fluid_buckets` 与 `code/mob_buckets` 的
语义）；对应口径见 ADR 与各数据文档。

判定方法：来源索引里 `yield_source = null` 的条目按 `source_type` + `unmapped_family` 分组，
同一组归并成一条需求。当前分布用 `bg index sources` 的 `by_yield_source` 字段看，
明细在 `build/<pack>/source_index.jsonl`。

## 1. 结构间距的分位数与方差（采集侧）

**要什么**：`structure-spacing` 的每个结构集合补充分位数与方差：`p25` / `p75` / `p90`、`varianceNN`、`maxNNBlocks`。

**现在为什么不够**：现有产物只给 `meanNNBlocks` 与 `medianNNBlocks`。下游要在「期望距离 / 中位数 / 保守估计」之间切换，三者的差别全在分布尾部；只有均值与中位数时，任何非对称分布都会被当成对称处理。原始最近邻距离样本没有导出，本侧无法重新求分位数。

**验收判据**：

- 同一集合的 `p50` 与现有 `medianNNBlocks` 一致。
- `p90 ≥ p75 ≥ p50 ≥ p25`，且 `maxNNBlocks ≥ p90`。
- 样本不足的组合（当前按配置间距兜底的那批）允许字段缺省，不得填零。

**不请求的部分**：由 `spacing` 反推期望最近距离（`spacingChunks × 16 / 2`）是本侧的兜底假设，不要求上游导出——它属于下游口径，上游给了反而会锁死换算法的余地。

## 2. 结构重叠与「同趟顺路」比例（采集侧）

`structure-interior` 已经给每个结构实例的包围盒、容器与专有方块，但没有**结构化地说明哪些
实例互相重叠**。本侧的旅行成本按「单结构最近距离」算，两个结构重叠时同一趟会被算两次，
耗时会偏高。

**要什么**：每个实例「与哪些其他实例的包围盒相交」，或直接给「重叠结构对 / 实例对」的比例。

**验收判据**：同一结构集合下该比例可算；样本不足的组合允许字段缺省，不得填零。

## 3. 明确**不要**放进 graph 的（边界约定）

- **时间与概率**：氧化/生长/孵化时长、每场凋灵能炸死几只、骨粉推进阶段数——
  这些是机制事实或标定项，本侧 `gamedata.py` 有唯一入口，进 graph 只会变成第二份真相。
- **数量**：每处多少容器、每箱多少件——采集侧的活。
- **下游口径**：TU 定义、评分档位、省不省一趟的判定，属于本侧策略，上游给了反而锁死换算法的余地。

## 不需要上游新增的

- **战利品表的权重**：上游 `facts/loot_table.jsonl` 按存在性语义丢掉了 `weight`
  （见 [ADR 0017](../adr/0017-loot-expectation-owned-downstream.md)），本侧改为直接解析原版
  数据包里的表，因此不需要上游补权重。原版表由 `bg data sync` 从
  `RecipeAnalysis/inputs/<pack>/data/minecraft/loot_table` 复制，不入库。
- **交易条款与配方折算**：`facts/trade.jsonl`、`facts/recipe.jsonl` 已存在且格式够用，
  本侧的 `trade_offer` / `item_convert` 两个 stat_type 与查询方法均已接入，不需要上游改动。
