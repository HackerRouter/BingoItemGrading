# ADR 0026：与 RecipeAnalysis 共用战利品表解析层

## 背景

两个项目读同一批原版数据包，语法层的判断完全一致：

| 位置 | modern（26.x） | legacy（≤1.20） |
|---|---|---|
| 函数数组 | `modifier` | `functions` |
| 条件 | 单数 `condition` | 数组 `conditions` |
| 条件内类型键 | `type` | `condition` |
| 序列 | 有 `random_sequence` | 无 |

RecipeAnalysis 的 `adapters/loot.py` 已经把这四件事处理干净（含「未知类型不静默丢弃」），
本项目的 `loot/expect.py` 又写了一版。两版的分叉是迟早的事——一边修了 `unenchanted_chance`，
另一边仍按 `chances` 数组读，同一张表在两边给出不同的掉率。

## 决定

抽出 `src/mcshared/`，只放**语法还原**：

- `loot.normalize_table(doc, table_id)` → `Table`（`Pool` / `Entry` 树，保留 `raw`）
- `loot.condition_type` / `normalize_conditions` / `normalize_functions` / `walk_entry`
- `loot.fact_payload(table)` → RecipeAnalysis 的事实形状
- `jsonio.read_json` / `read_json_object`

不放的东西同样重要：

- **语义**（`serializer → station`、legacy 表映射）留在 RecipeAnalysis 的 IR 层。
- **概率与代价**留在 BingoItemGrading 的 `loot/expect.py`：上游按存在性求解，刻意不算数量。

## 接线方式（临时）

物理副本只有一份，在 `BingoItemGrading/src/mcshared/`。
RecipeAnalysis 通过 junction 引用：`RecipeAnalysis/src/ra/mcshared` → `BingoItemGrading/src/mcshared`，
`ra` 侧以 `ra.mcshared` 导入，`bingo_grading` 侧以顶层 `mcshared` 导入。

两侧的 `.gitignore` 都排除了 junction 挂载点——否则 git 会把同一份代码当普通目录再提交一遍。

抽取稳定后可以各自独立发布，届时删掉 junction 与 `ra/adapters/loot.py` 里的再导出即可，
两边的调用点不需要改。

## 判据

改动前后必须逐字节一致，两个层次各有一个校验脚本：

- `tools/check_loot_parity.py`：1447 张原版表 + 6 张地形包覆盖表，比较
  `fact_payload` 的 JSON 文本与 `missing` 列表，**0 处差异**。
- `tools/check_expect_parity.py`：1447 张表 × 两种工具条件，比较 `per_item` 与
  `total_items`，**0 处非预期差异**（3 张 `equipment/*` 是有意的修复，见 ADR 0027）。
- RecipeAnalysis 全量测试 455 通过；重跑 `ra ingest --label 26.3` 后
  `facts/loot_table.jsonl` 的 SHA-256 不变。

## 后果

- 新增实例：`tools/check_loot_parity.py` 依赖上游项目 `RecipeAnalysis` 存在；`data/upstream/` 不入库，
  所以它是**本地校验**，不是 CI 守卫。
- 代价：`mcshared` 没有独立版本号与发布流程，改动同时影响两个仓库。`SCHEMA_VERSION`
  只标示归一形状，不解决协同问题。这是「暂时」的含义。
