# 测量对象与来源对象是两套标识

## 背景

来源索引按**获取途径的标识**组织：战利品表路径（`minecraft:chests/village/village_toolsmith`）、方块 ID、实体 ID。世界统计按**测量的标识**组织：结构集合（`minecraft:villages`）、矿石方块（`minecraft:gold_ore`）、实体类型（`minecraft:pig`）。

两套标识不能合并成一个。同一结构集合下有多个箱子表（村庄有武器匠、工具匠、制图师等十余张），统计只测到集合粒度；反过来，同一个箱子表也可能被多个结构集合共用。强行统一会丢掉其中一侧的信息。

## 决策

来源记录同时带 `subject`（来源对象）与 `stat_subject`（统计键）：

- `block_drop`：`stat_subject` = 方块 ID。
- `mob_drop` / `shear`：`stat_subject` = **基础实体 ID**，去掉变体后缀（`minecraft:sheep/black` → `minecraft:sheep`）。实体密度按类型测量，不按毛色。
- `loot_table` / `suspicious_block`：`stat_subject` = 结构集合 ID，由 `data/knowledge/structure_sets.toml` 按最长前缀解析；解析不出时为 `null`。
- `trade`：`stat_subject` = 来源对象本身，但第一版没有对应统计类型。

`null` 不是「确定做不到」，而是「这条来源查不到统计」。缺口报告按类型列出这些来源，交给补测或补映射。

## 后果

- 结构集合的统计能被十张村庄箱子表共用，不必重复测量。
- 映射表是数据，不进代码；新增结构只需加一行前缀。
- 未映射的来源在报告里可见，不会被静默当成有数据。
- 变体（羊毛颜色、蘑菇牛颜色）不各自测量，密度归到基础实体。

## 替代方案

让统计侧按表路径测量：同一村庄要被测量十余次，且各表的箱子数量与位置关系无法从表路径恢复。让来源侧统一到结构集合：丢掉「具体哪张表」的信息，策略注册时无法指向单一箱子。

细节见 [`sources.md`](../data/sources.md) 与 [`stats.md`](../data/stats.md)。
