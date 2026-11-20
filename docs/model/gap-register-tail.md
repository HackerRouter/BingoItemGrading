# 缺口的影响范围与后续动作

条目编号与 [`gap-register.md`](gap-register.md) 连续。

## 2. 影响范围一览

| 缺口 | 受影响目标数 | 典型例子 |
|---|---|---|
| D3b 跑图系数 | **全部**（跑图密集的翻 2.5 倍） | `diamond` 11.38 / 26.01、`gold_ingot` 5.69 / 13.01 |
| D1 挖矿 | 9/54 的最优路线是挖矿，全部受影响 | `copper_ingot` 7.85（应更低）、`quartz` 17.07 |
| S1 结构间距 | 1–2 个目标 | `pillager_outpost` 的箱子 |
| S2 交互来源 | 3–5 个目标 | `honey_bottle`、`milk_bucket`、羊毛 |
| D2 剪枝口径 | 全部（保守偏差，已缓解） | — |
| A1 尾部 | 全部（缺一维） | — |
| A3 分层代价 | 袭击类 + 全部交易类 | `totem_of_undying`、`ender_pearl` |

## 3. 明确不修的：「合法但荒谬」的来源

模型只问「最便宜」，不问「玩家品味」。实测 `string` 走 `kill:cat`、
`bone` 走 `loot:abandoned_camp`——这些**不是 bug**，是「一般人没想到的路径」。

判断标准只有一条：**这条路线在游戏里做得到吗**。做得到就保留，哪怕它看着离谱。
Bingo 的实际玩法里，顺手打猫取线完全成立。

真正要修的是「做不到却被算成做得到」（截断路线、悬空前置），以及「做得到但代价算错」
（D1、D3b）。不修「做得到但因为品味不想选」。

### 3.1 明确不修的数据/建模缺口

这条是「技术上能做、但没有可辩护的依据」，硬做只会让数字看起来精确而实际更假：

| 缺口 | 为什么不做 | 代价 |
|---|---|---|
| 群系自然刷怪（H1） | 「在某个群系待多久」没有数据也造不出假设，结果取决于玩家在干什么；填任何数都是拍脑袋 | `ghast_tear` 保持 `inf` |
## 4. 待提交上游的新需求

以下两条不在 C1–C17 / R1–R6 里，是这一轮建模才识别出来的。
`collector-requirements.md` 已加编号索引，正文放在这里，可直接整段复制给对方。

### C19 · 结构的生物生成规则（R A 已交，已接入）

**状态**：RA 交出了 `spawn_tables.jsonl`（887 行），下游已接入为 `mob_spawn`
stat_type（850 行），结构权重、袭击波次都进了动作图。本节的“需要什么”
可保留作为数据字典，下游验收已完成（见 `covered-register.md`）。

**问题**：一批生物由结构自己持续产生，与「结构里放了什么方块」无关：

| 生物 | 结构 | 下游后果 |
|---|---|---|
| `evoker` | 林地府邸、袭击 | `totem_of_undying` 算不出 |
| `vindicator` | 林地府邸、袭击 | `iron_axe` 少一条路 |
| `guardian` / `elder_guardian` | 海底神殿 | `prismarine_shard` 算不出 |
| `wither_skeleton` | 下界要塞 | 只能借「要塞刷怪笼」这一条（而它不是笼子刷的） |
| `ghast` | 下界荒地 | `ghast_tear` 算不出 |

**为什么静态扫描拿不到**：
`structure-interior` 的 `spawnersPerStart` 与 `entitiesPerStart` 统计的是
**结构生成时嵌入的方块与实体**（`mob_spawner|blaze`、`chest_minecart`、`armor_stand`）。
上表这些生物在玩家不在场时不存在，静态扫描看不到；`entity-census` 也只统计
陆生/水生动物。

**需要什么**：按**刷怪权重**而不是实测密度。对每个结构给一张
「该结构会产生哪些生物、权重多少」的表。RA 已按此产出 `spawn_tables.jsonl`。

**仍缺的一半**：`biome:*` 那 811 条没有对应的行程成本，所以只能给
`ghast_tear` 这类「只在群系里刷」的生物留口子（见 H1）。

### R7 · 结构内生物与容器的 processor 归属

与 C19 同源、但属 RecipeAnalysis 侧：`structures/*.json` 的 `processors` 里
既有「把 `loot_table` 写进容器」的规则（R4 第 2 点），也有「插入实体/刷怪配置」的
规则。目前 `template_containers.jsonl` 只覆盖前者的一半。

**原案例已撤回**：这条需求原来是拿 `monument` 的 `containers = 0.0` 当证据的，
但海底神殿在 vanilla 里**根本没有战利品箱**（只有 8 个藏金室与海绵房间），
`containers = 0.0` 是正确值而非缺口。所以要继续这条需求，得先重新确认
vanilla 里到底哪个结构真的把带 `loot_table` 的容器交给 processor 生成——
目前**没有确认过的案例**。`pillager_outpost` 曾是候选，但它的箱数问题是
缺 `structure_density` 集合（C12 范畴），与 processor 无关。

**状态**：需求保留，但暂无验收目标。没有案例就不提交上游。
