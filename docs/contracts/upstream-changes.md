# 需要上游改什么（总表）

三行，只列**阻塞当前进度**的项。详述见 [`collector-contract.md`](collector-contract.md)。

| 上游 | 改什么 | 状态 |
|---|---|---|
| `RecipeAnalysis` | `_collect_refs` 跳过 `replaceable_blocks` / `valid_base_block` 子树，不产 `slot=block` 引用 | ✅ **已改**（`SKIP_SUBTREES`） |
| `WorldGenStatsCollector` | 跑末地与下界；群系级补纵段分解与非矿石方块 | ✅ **已改**（`ore-stats` 三维度 + `sectionProfiles` + `bulk` 类） |
| — | 当前无阻塞项 | — |

## 已撤回

- **R1 / R2（战利品 `weight` 与分组语义）**：改由本项目自己解析战利品表计算，见 [ADR 0017](../adr/0017-loot-expectation-owned-downstream.md)。上游保持存在性语义不动。
- **C8 / C10 / C13**：`ore-stats` 一次解决——三个维度都测了、群系级带 `sectionProfiles` 纵段、非矿石方块走 `bulk` 类（`chorus_plant` 在末地高地 43.25/区块，`ancient_debris` 在下界荒地 1.63/区块）。

## 非阻塞、按需再做

| 编号 | 内容 |
|---|---|
| C9 | 稀有群系分层采样，或为密度配 95% 置信区间（恶地只有 38 区块，`reliable: false`） |
| C11 | 地下空洞率 / 通道密度（「去矿洞挖」的代价） |
| C12 | 群系内结构间距（末地城在高地内 vs 高地外） |
| R4 | 模板补 `chest_count` 与主体模板标记（影响 `chests_per_structure` 精度） |
| R6 | 末地/下界无 `world:` 节点 → 已知限制，**不必改** |

## 本轮已完成的上游交付

| 组 | 内容 |
|---|---|
| C1–C5 | 产物 `target`（版本、种子、地形包哈希、jar 哈希）、结构化 `range`、`units`、按维度分层 |
| C6 | `biome-patch`：群系斑块规模、地表开放性、邻接 |
| C7 / C8 / C10 / C13 | `ore-stats`：三维度群系级矿石与方块密度、暴露分解、纵段剖面 |
| R5 | 跳过 `replaceable_blocks`，消除假关联 |
