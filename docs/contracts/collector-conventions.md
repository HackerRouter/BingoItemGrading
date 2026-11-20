# 采集器数据形态与验收

节号与 [`collector-contract.md`](collector-contract.md) 连续。

## 5. 数据形态约定（下游消费侧）

下游导入器读每个 `<analyzer>.json` 的 `result`，按 `schemaVersion` 分派。契约：

| 项 | 约定 |
|---|---|
| 编码 | UTF-8，无 BOM |
| 缺失值 | **`null` 表示「没有测到」，字段缺失表示「该口径不适用」**。两者都不等于 0 |
| 零值 | 只有真测到 0 才写 `0`。样本不足写 `null` + `reliable: false`，不要写 0 |
| 分母 | 每个比率/平均值必须在 `note` 或 `units` 里说明分母 |
| 维度 ID | 命名空间形式 |
| 群系 ID | 命名空间形式，且与 `biome-histogram` 同口径（地表群系） |
| 方块 ID | 命名空间形式，不带 `item:` 前缀 |
| 结构标识 | 同时给 `set`（结构集合）与 `structureIds`（变体），下游按 `set` 聚合、按 `structureId` 认变体 |
| 浮点 | 保留原值，不要在采集侧四舍五入 |

`schemaVersion: 2` 的完整形状：

```json
{
  "analyzer": "ore-exposure",
  "schemaVersion": 2,
  "generatedAt": "2026-11-06T05:42:38.163Z",
  "target": { … },
  "range": { … },
  "units": { … },
  "config": { "yMin": null, "yMax": null },
  "ok": true,
  "errors": [],
  "result": { "minecraft:overworld": { … } }
}
```

---

## 6. 下游需要配合的改动（我方）

| # | 改动 | 状态 |
|---|---|---|
| S1 | 导入器按 `schemaVersion` 分派，旧形态明确报错 | ✅ 已实现 |
| S2 | `biome_patch.vertical_condition_prob` 取 `openSurfaceShare` | ✅ 已实现 |
| S3 | 新增 `ore_density` 统计类型（群系级，不含暴露） | ✅ 已实现（与初稿的「给 `ore_exposure` 加群系行」不同，见 ADR 0012） |
| S4 | 新增 loot 期望计算器，消费上游 `loot_table` + `template` 事实 | ✅ 已实现（本侧解析数据包战利品表，见 ADR 0017） |
| S5 | 新增实体可遇见群系占比，消费上游群系 `references` + 本侧群系权重 | ⬜ 阻塞于上游去噪（R3） |

---

## 7. 执行顺序与验收

**第一批（阻塞下游 P3）— ✅ 已完成**
1. C1 + C2：头部标识与种子落盘
2. C3：`result` 按维度嵌套，升 `schemaVersion: 2`
3. C7：群系级矿石统计（以独立分析器 `biome-ore` 实现）

验收结果：`target.dataPacks[0].sha256 = f44ef3f9…`、`seed = 439625976969540166` 可读；山地绿宝石 `1.74/区块`、恶地金矿 `26.56/区块`，非零且可归因；但两者均为 `reliable: false`，数值尚不可用（见 C9）。

**第二批 — ✅ 已完成**
4. C6：`biome-patch`（55 个群系）
5. C4 + C5：结构化 `range` 与 `units`

验收结果：下游 `bg data ingest` 报告的 `unmeasured_stat_types` 只剩 `loot_expectation`。

**第三批 — ✅ 已完成（2026-11-11）**
6. C8：多维度预生成与分析

验收（基于 `2026-11-11T16-05-19-027Z`）：

- `summary.dimensions = [overworld, the_nether, the_end]`，三维度各有 `ore-stats.<dim>.json` 与 `structure-interior.<dim>.json`。
- 下界矿石实测：`ancient_debris` 997 块、`nether_gold_ore` / `nether_quartz_ore` 均有非零密度行（下游 `ore_density` 从 0 条下界行升至 **79 条**，末地 95 条）。
- 下界结构 4 个（`bastion_remnant` / `fortress` / `nether_fossil` / `ruined_portal_nether`）、末地 1 个（`end_city`）有了实测箱数与方块统计。
- C15 地牢深度轴同步落地，下游已导入为 `by_depth`。
- **未覆盖**：`entity-census` 仍只有主世界（`result` 只有 `minecraft:overworld`）。这一项不再作为需求——C17 已判定脱离玩家不可测。

**当前状态：C1–C8、C13–C16 已完成，C9–C12 为可选项，C17 已撤回。**

**通用验收**

- 同参数重跑两次，产物逐字节一致（`generatedAt` 除外）。
- 被跳过的条目一律进 `unsupported` 并写原因，不允许静默跳过。
- 样本不足时输出 `reliable: false`，不输出看起来正常的数。

---

## 8. 明确不做

- **不解析战利品表**。那是 `RecipeAnalysis` 的职责，见第 4 节。
- **不模拟刷怪**。理由见第 4 节。静态列表由 `RecipeAnalysis` 提供。
- **不为兼容旧 `result` 形态加分支**。下游只有一个消费者。
- **不预估出生点分布**。下游用 `biome-histogram` 的地表面积占比作代理，并在文档里标明这是代理。真测需要大量出生点模拟，收益远低于成本。
- **不在 `ore-exposure` 里塞非矿石方块**。下游 1425 条非矿石方块来源（木头、圆石、沙、陶瓦）本来就不该查暴露密度——它们遍布世界，代价由群系覆盖与配方链给出。要密度就单列分析器。
- **不追求稀有结构的统计显著性**。府邸、神庙这类 1 个样本的结构，下游按 `confidence: low` 处理；靠扩大半径解决不经济，靠种子复现验证即可。
