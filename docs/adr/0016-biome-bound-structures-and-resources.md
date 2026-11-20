# 结构与资源绑定特定群系时怎么建模

## 背景

末地城只生成在末地高地与末地内陆，`chorus_plant` 只生成在 `end_highlands`。这类「结构与资源被限制在某几个群系」的情况在数据包里很常见（下界要塞只在特定群系、远古城市只在深暗之域）。

问题：统计是按维度测的（`structure_density` 给的是末地全域的最近邻距离），而实际约束是群系级的。这个差距要怎么补？

## 决策：结构与资源分开处理

### 结构侧：实测间距直接用，不再乘群系面积

`structure_density.expected_nearest_distance` 是**实测**的：在真实世界里量每个结构起点到最近起点的距离。如果末地城只生成在末地高地，这个实测值**已经包含了「要找对群系」的成本**——因为测量时那些非高地位置的末地城确实不存在，它们之间的距离自然被拉长。

所以：

```
末地城代价 = 进入末地 + 实测间距      ✓
末地城代价 ≠ 进入末地 + 实测间距 ÷ 高地面积占比    ✗ 重复计算
```

用群系面积去调整实测间距，等于把「只有高地有」这件事算了两遍。这是本节最重要的一条。

**一个真实缺口**：实测间距是「从任意点出发」，而玩家起点可能在 `end_barrens`。从高地内部出发找末地城，应该比全域间距更短。当前只有一个数，分不出「从群系内出发」与「从群系外出发」。这与 C10 同类，属于「群系内结构间距」，暂记为 C12。

### 资源侧：必须显式建模两段

`chorus_plant` 不是结构，没有实测间距。它的代价需要拆成两段：

```
草甸/高地类资源代价 = 进入维度 + 找到该群系 + 在群系内采集
```

三段各自的输入：

| 段 | 需要的统计 | 现状 |
|---|---|---|
| 进入维度 | 与结构共用，一次 | 由 P3 的 DAG 处理 |
| 找到群系 | 该群系在维度的 `area_fraction` 与斑块 `mean_area` | `biome_patch` **有**（主世界）；末地**没有** |
| 群系内采集 | 该群系内该方块的数量密度 | `ore_density` **只覆盖矿石**；非矿石方块无类型 |

**「找到群系」为什么不等于 `1/面积占比`**：群系是连片的，玩家进入后能持续走下去。面积占比给的是「随机一点落在该群系的概率」，而实际要走的是「到最近斑块的距离」。后者由斑块平均面积与间距决定，所以必须用 `biome_patch` 的 `mean_area` + `patch_density`，不能只用 `area_fraction`。

### 两者的耦合：共享「到达该群系」节点

末地城与 `chorus_plant` 都在 `end_highlands`。玩家跑一趟同时拿两样，如果各自算一遍「找到高地」的代价，就是重复计价。

这正是计划书 P5 的**共享前置**：在 DAG 里建一个 `event:end_highlands` 节点，两条来源都挂在它下面。

```
event:the_end          （进入末地）
  └── event:end_highlands   （找到高地，代价由 biome_patch 给）
        ├── end_city        （间距由 structure_density 给）
        │     └── elytra / shulker_shell
        └── chorus_plant    （群系内方块密度）
              └── chorus_fruit
```

`event:end_highlands` 只算一次，两个子节点各加自己的段代价。这样「顺便拿」在模型里自然成立，不需要额外的折扣系数。

## 数据缺口（已记为上游需求）

| 编号 | 缺口 | 影响 |
|---|---|---|
| C8 | 末地完全没有统计 | 末地所有物品的代价无输入 |
| C12 | 群系内结构间距 | 分不出「从群系内出发」与「从群系外出发」 |
| C13 | 非矿石方块的群系级密度 | `chorus_plant`、木头、沙都在这一类 |

C13 是 `biome-ore` 的推广：那个分析器只统计矿石（16 种），而 `chorus_plant`、`chorus_flower`、`end_stone`、各种原木都需要同样的「群系内每等效区块数量」。建议把它改成接受方块白名单，而不是硬编码矿石列表。

## 上游数据问题（已核实）

### 上游不存在末地世界节点

`graph.json` 里只有 `world:minecraft:overworld`，**没有** `world:minecraft:the_end` 或 `world:minecraft:the_nether`。上游按存在性语义求解，不判维度，所以把末地特性也挂在 `overworld` 下：

```
block:minecraft:chorus_plant <- ['world:minecraft:overworld']  （错，chorus 只在末地）
```

因此**维度判定不能依赖上游的 world 节点**。本项目采用三级依据（见 `docs/sources.md`）：前置世界节点 → 前置结构 → 名称关键词。

### 上游把 `replaceable_blocks` 当成「该特性放置的方块」

`feature/crimson_fungus` 的 `replaceable_blocks` 里列了 `minecraft:chorus_plant`（真实数据：菌类可替换植物类方块）。上游据此产出一条：

```
block:minecraft:chorus_plant <- ['world:minecraft:overworld']
    family=worldgen  meta={'slot': 'block', 'source': 'feature/crimson_fungus'}
```

`crimson_fungus` 是下界特性，与紫颂植物无关。上游把「能替换的方块」与「会放置的方块」混为一谈。

**处理**：不需要为它加区分字段。「可替换」是判断生长条件的语义，下游没有消费场景，**上游直接跳过 `replaceable_blocks` 整个子树即可**。

对我们影响有限：`placement.py` 只用它判 `structure_only`，而 `chorus_plant` 本来就不是结构专属。

## 后果

- 结构代价不需要为群系归属做任何调整，这一条消除了一个容易犯的重复计算。
- 资源代价必须两段，且要共享前置节点，否则「顺便拿」会被算成两次。
- 末地、下界在统计到位前，相关物品的代价只能是「未知」，不能拿主世界数据顶替。
