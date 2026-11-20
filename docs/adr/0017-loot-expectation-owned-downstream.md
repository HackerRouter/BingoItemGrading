# 战利品期望由本项目算，不由上游算

## 背景

上游 `RecipeAnalysis` 的求解语义是**存在性**：「只要存在某个世界使物品出现，就判可达」。按这个语义，掉落权重与分组结构确实不影响布尔结论，所以它把 `weight` / `quality` 从事实里排除掉了——这是刻意的，不是遗漏（`adapters/loot.py` 的 `walk_entry` 把这两个键列入排除项）。

但难度评分需要的是「有多容易」，正是那条语义认为无关的部分。于是出现了分工问题：期望值该由谁算？

## 决策

**本项目自己解析战利品表算期望值。上游只保留存在性判定，不补 `weight`。**

## 理由

1. **语义不同，不该由同一个模块承担**。存在性是布尔量，期望是实数量。上游明确不判位置、不判数量、不判概率，这些都是下游的需求。
2. **上游缺的不只是 `weight`**。26.3 的数据包用 `modifier`（不是 `functions`）、`condition`（不是 `conditions`）、`table_bonus` 带概率表、`loot_table` 条目的表 ID 在 `value`（不是 `name`）。这些若由上游归一化，等于让上游为下游的口径做适配；不如下游直接读原始数据包。
3. **地形包会覆盖战利品表**。已核实：`FASBingoWorldgen` 覆盖了 `entities/enderman` 与 `gameplay/piglin_bartering` 两张表。覆盖关系必须按「原版 → 版本层 → 包内 data/」叠加，这属于「这个地形包怎么改的」问题，不是「原版数据长什么样」问题。
4. **箱子数在上游事实里已有**。`facts/template.jsonl` 的 `loot_tables: [{pos, table}]` 给出每个模板挂了哪些箱子（429 个模板），不需要上游额外工作。

## 实现

| 模块 | 职责 |
|---|---|
| `src/bingo_grading/loot/tables.py` | 分层加载：原版打底，地形包按版本层与 `data/` 覆盖。整文件替换，不做字段合并 |
| `src/bingo_grading/loot/expect.py` | 期望计算：`E = Σ_pool E[rolls]×P(池条件)×Σ_entry P(选中)×E[数量]` |
| `src/bingo_grading/stats/importers/loot.py` | 结合模板事实，写 `loot_expectation` 统计行 |
| `bg data loot` | CLI 入口 |

支持与不支持的边界写在 `expect.py` 的模块 docstring 里。要点：

- **工具条件是参数，不是常数**。`tool/can_shear`、`tool/can_silk_touch` 的成立与否直接改变结果：橡树叶带剪刀时掉树叶、木棍概率归零；徒手时掉树苗 5%、木棍 2%。所以两种都算，用 `condition` 区分（`tools=present` / `tools=absent`），两行共存。
- **附魔按无附魔级**：`table_bonus` 取 `chances[0]`。
- 无法求值的（`tag` 条目、`dynamic` 条目）进 `unsupported`，不静默当 0。

## 验收

已核实的结果（`26.3`）：

| 表 | 期望含义 |
|---|---|
| `chests/simple_dungeon` | 每次开箱 21.7 件，骨头 3.375（=3 次投掷 × 10/40 × 1–8 均值 4.5） |
| `blocks/oak_leaves`（徒手） | 木棍 0.03（2% × 1.5）、树苗 0.05（5%） |
| `chests/buried_treasure` | 铁锭 9.29/箱（藏宝图链的价值由此可算） |
| `chests/end_city_treasure` | 铁锭 2.70、钻石 1.01/箱 |

## 后果

- 上游需求 R1（保留 `weight`）与 R2（保留分组语义）**撤回**，不需要上游改。
- 下游多一个可独立调口径的模块：是否计 `bonus_rolls`、是否把 `conditions` 按 1 算，都改这一处。
- `loot_expectation` 不再出现在采集侧的「缺测」清单里，改由 `bg data loot` 的报告说明覆盖情况。

## 替代方案

**继续要求上游保留 `weight`**：上游要为一件事实现两套语义（存在性给求解器、期望给下游），且下游改口径就要动上游。已放弃。
