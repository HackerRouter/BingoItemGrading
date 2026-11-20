# 上游来源索引的接入方式

> **后续修订**：`probability` 字段仍保留，数值来自 `gamedata.PROBABILITY_ROWS`；战利品来源改用 `yield_per_trigger`（ADR 0027）。

## 背景

可达性由上游项目判定，本项目不重复解析数据包。上游产物是 Horn 规则集（`graph.json`：每条规则 `head ← body`，三值状态），不是本模型需要的「每条来源一行」的索引。

## 决策

本项目自带适配器 `src/bingo_grading/sources/`，从 `graph.json` 导出 `build/<label>/source_index.jsonl`。每个可达物品的每条非合成来源输出一行，字段：

| 字段 | 含义 |
|---|---|
| `item` | 物品命名空间 ID |
| `source_type` | 来源类别，取值见 `docs/sources.md` |
| `hard_prereq` | 硬前置节点，递归展开到 `world:` / `structure:` / `tool:` / `station:` / `assume:` / `enchant:` |
| `probabilistic` | 是否概率性来源 |
| `probability` | 概率值，来自 `data/knowledge/probabilities.toml` |
| `is_reverse` | 是否为反向合成边 |
| `primary_source_hint` | 主来源提示，第一版恒为空 |
| `rule_ref` | 上游规则 ID，用于追溯 |

合成配方不产生来源行：合成链由展开器递归处理，把配方当来源会让同一物品在槽位表里重复计数。

适配器只读上游产物，不写入上游目录；上游缺失时只影响依赖它的槽位枚举，P1–P3 的统计与聚合不受影响。

## 后果

- 上游产物格式变化只改适配器一处，契约字段不变。
- 每条来源都能回到上游规则 ID，可复算。
- `hard_prereq` 的递归展开可能撞上环：环上的分支标记后跳过，不静默丢弃。

## 替代方案

让上游直接产出本模型的索引：把下游的字段需求压进上游，上游一改下游就要跟着改，且上游的「存在性语义」与本模型的「难度语义」边界会混在一起。
