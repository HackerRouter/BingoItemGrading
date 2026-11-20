# 硬缺口

条目编号与 [`gap-register.md`](gap-register.md) 连续。

### 1.2 硬缺口（P1）

**H1 · 群系自然刷怪（2026-11-15 已用近似补上）**

结构类与事件类已补齐（见 `covered-register.md` 的 C19）：
`mob_spawn` 现在带了 RA 刷怪表的 850 条规则，结构权重与袭击波次都进了动作图。
`prismarine_shard` = 75.89、`wither_skeleton_skull` = 692.14、
`totem_of_undying` = 30.50。

`biome:*` 那 811 条**当时定为不修**，理由是「停留时间没有数据也造不出可辩护的假设」。
后来改了做法：不猜停留时间，改用**刷怪表的权重占比**推「平均打死几只才出一只想要的」：

```
每趟成本 = 走到该群系（biome_search_cost，面积占比法）
         + (群系总权重 / 本人权重) × (等一只 + 打死一只)
```

`等一只` 取 `tuning.NATURAL_SPAWN_SECONDS = 5.0`——**这是全仓唯一一个纯拍的时间常量**，
注释里写明了。它只在 `_structure_mob_placed` / `_structure_mob_weighted` / `_raid_mob`
全都不出活时才用，也就是只有「不在任何结构、也不是袭击成员」的生物才走这条路。
方向在两种玩法下**相反**：蹲点刷（真实 1–2 秒/只）时偏保守，跑图顺路时偏乐观；
`roam:` 的语义是前者。所以有数据来源时优先不用它。

实测效果（`ink_sac` / `pufferfish` 的变化最有说服力——它们原来的路线是
「钓鱼钓到垃圾」，换成直接打鱿鱼/河豚后回到合理量级）：

| 物品 | 修前 | 修后 | 新路线 |
|---|---|---|---|
| `ghast_tear` | **inf** | **30.42** | `roam:ghast:soul_sand_valley`（占 monster 权重，平均打死几只才出 1 只） |
| `ink_sac` | 37.97 | **1.98** | `roam:squid:river`（鱿鱼是河里唯一的水生生物， 占比 100%） |
| `pufferfish` | 28.52 | **4.40** | `roam:pufferfish:warm_ocean` |
| `ender_pearl` | 40.53 | **27.77** | `roam:enderman:warped_forest`（比猪灵交易 快） |

`inf` 从此清零。代价是这几个数**只到量级可信**，别拿它做百分比比较。
（表中数字是 2026-11-14 权重产出修正后的值，见 H4 末尾那段。）

**H2 · Boss 召唤（2026-11-14 已补）**

凋灵之星来自**玩家召唤的凋灵**（4 灵魂沙 + 3 凋灵骷髅头）。这条走 `constructs`
系统实现，与末地门同一个机制：`wither:summon` 的输入递归定价，加 60 秒战斗时间。

实测：`nether_star` `inf` → **2063.27**（灵魂沙 + 3 个骷髅头 + 战斗；
骷髅头单价从 230.55 修正到 692.14，见 H4 末尾）。修这条时顺带找到一个真 bug：
`best_whole_cost` 的 memo 只按 `(item, demand)` 缓存，不区分 `seen`，把
「因环截断」的 `None` 缓存后污染了同一次求解里的其它路径。

**H3 · ~~`monument` 的结构内容全空~~（已撤回：原判断是错的）**

原先这里写「`containers = 0.0`、`blocks_per_start` 空，箱子由 processor 放置」。
核对数据后**三条都不成立**：

- `containers = 0.0` 是**正确的**——海底神殿在 vanilla 里没有战利品箱，
  只有 8 个藏金室（金块）与海绵房间。这里不该有容器。
- `blocks_per_start` **不空**：27 种方块，`prismarine` 5559.4、
  `prismarine_bricks` 5072.2、`stone` 1348.0、`gold_block` 6.4、`sea_lantern` 103.4
  （每处）。海晶类方块与潮涌核心的方块路线本来就有数据。
- 没有 `entities` / `spawners` 也不是缺口：守卫者走 `mob_spawn` 的
  `structure:*` 权重（占比 100%），不依赖容器内容。

所以这一条从「硬缺口」撤回。唯一残留的疑问是数据内部不一致：
`blocks_per_start` 里有 `minecraft:chest: 0.6`，而 `containers` 是 0.0——
两者本应一致（有 chest 方块就该有容器）。海底神殿没有箱子，所以**要么
采集器把某个方块误认成 chest，要么 `blocks_per_start` 的方块统计里混进了
别的东西**。这条未修，不影响任何数值。

**H4 · 装备掉落（手持/穿戴物）的概率不在战利品表里（已用兼容层顶上 1 条）**

MC 1.21 起，「生物手里的装备死亡时掉落」这一层从战利品表移进了实体类的
`dropCustomDeathLoot`。`entities/drowned.json` 现在只有 `rotten_flesh` 和
`copper_ingot` 两个池，**三叉戟那一池整个不见了**。

上游 RA 能指出「哪个槽位的装备会掉」（`drops_source` 的
`meta.slot = MAINHAND, trigger = entity_death`），但拿不到概率。所以
`source_index` 里这类记录有 40 条 `yield_per_trigger = None`：

| 类别 | 例子 |
|---|---|
| 手持武器/工具 | `trident`(drowned)、`stone_sword`(wither_skeleton)、`iron_sword`(zombie/vex)、`crossbow`(pillager)、`bow`(illusioner)、`iron_axe`(vindicator)、`golden_axe`(piglin_brute)、`fishing_rod`(drowned)、`iron_shovel`、`iron_spear`、`warped_fungus_on_a_stick`、`saddle` |
| Boss / 特殊 | `nether_star`、`dragon_egg`、`dragon_breath` |
| 杂项 | `magma_cream`(magma_cube)、`nautilus_shell`(drowned)、`turtle_egg` |

**头颅不属于这一类（2026-11-14 更正）**。原先这张表把头也列进来是错的，
它们的机制完全不同：

- `wither_skeleton_skull` 是**普通战利品**，在 `entities/wither_skeleton`
  的第三个池里（0.025/只，抢夺每级 +1%），已经走 `haunt:` 路线，从来不是缺口。
- `creeper_head` / `zombie_head` / `skeleton_skull` 是**闪电苦力怕炸死**时掉：
  一道闪电把苦力怕变成闪电苦力怕，它炸死别的生物才掉那个生物的头，
  **一个闪电苦力怕只出一个头**，与装备机制无关。
- `piglin_head` 同属这类特殊事件。
- `player_head` **玩家获取不到**（只能击杀玩家或指令）。
- `dragon_head` **不走闪电**：末地船的船头挂着 `dragon_wall_head`，
  挖掉就是龙头。`structure_content` 里 `minecraft:end_city` 有
  `dragon_wall_head: 0.4848`（每处平均 0.48 个），已接成
  `loot_block:dragon_head:end_cities` = **163.95 TU**。
  `skeleton_skull` 同理（远古城市每处 3 个）= 31.75 TU。

**为什么「挂墙变体」要单独处理**：结构里的龙头/头颅几乎都以
`*_wall_head` / `*_wall_skull` 形态生成，而物品名是 `dragon_head`。
上游 RA 的 `code_link` 里有 7 条 `loot_alias` 记着这件事
（`dragon_head` ← `dragon_wall_head`），但那是「掉落表相同」的语义；
下游要的是「结构内容里这个方块叫什么名字」，所以
`context._with_wall_variants()` 按命名约定拼变体名，查
`blocks_per_start` 时两个名字一起试。

这条**不建模**：闪电是天气事件，命中苦力怕再炸中特定生物，整条链的概率
既没有数据也造不出可辩护的假设，和 H1 的「群系停留时间」是同一类问题。
目前这几个头在表里是 `None`（无路线），这是正确的表达——它们确实不是
Bingo 卡池里能稳定获取的物品。

修这条时顺带发现两个真 bug，都不是建模问题而是**关联错**：

| 现象 | 根因 | 修法 |
|---|---|---|
| `skeleton_skull` 1560406 TU / 20 分 | 它的 `block_density` 只数到 33 块（就是远古城市那 3 个/处），散点矿模型按 `1/ρ` 算出要挖 2000 块岩层 | `_structure_placed()` 改成**总是并列**，不再只当最后退路；引擎选「跑一趟远古城市挖 3 个」→ **31.75 TU / 5 分** |
| `player_head` 3.10 TU（走 `interact:player_head:bee_nest`） | `_mob_interact()` 把所有 `bridge:` 前缀的记录都转给 `_block_interact()`，而后者硬编码查 `bee_nest`/`beehive` | 只对 subject 含 `honey`/`beehive` 的走取蜜，其余记「未建模的行为」→ `player_head` 变 `None` |

第二条的波及面比头颅大：`filled_map`（制图师给地图）、`written_book`（书与笔）
共用 `bridge:behaviour:<name>:0` 这个 subject 形状，早先一律被当成取蜜。
（现状：上游已把这两条挪到 `bridge/item_conversion`，本侧按 `convert` 接入——
输入物品被消耗、右键一下即换，不叠探索行程，见
`docs/contracts/upstream-requirements.md` §7；`player_head` 仍无路线，上游把它标成不可达。）


三叉戟已在 `PROBABILITY_ROWS` 登记（$0.0625 \times 0.085 = 0.531\%$，
平均 188 只溺尸出一把），`_mob()` 在 `yield_per_trigger` 为空时退到该值。
其余 39 条仍是缺口。

**但不建议继续手工登记**：三叉戟接进 `_biome_mob_weighted` 后算出
「打死 1158 只怪、约 1324 TU」，比试炼大厅（305）贵 4 倍。这个方向没错
（Bingo 时限内不会有人专门刷溺尸场），但说明**逐只刷怪模型不适用于
低掉落率来源**——现实里溺尸农场一小时出 3–10 把，差 8–26 倍，因为农场
同时刷多只而模型按「一次一只」串行计价。

真要解决，需要上游透传 `dropCustomDeathLoot` 的 `chance` 常量，**并且**
另立一个「农场吞吐」概念（每小时产出率）。前者是数据需求，后者是没有
数据支撑的建模选择，两者都没有就先不动。

**顺带修正的产出放大（2026-11-14）**：接三叉戟时发现
`_structure_mob_weighted` 与 `_biome_mob_weighted` 都写
`yields = kills * per_kill`——成本按「打死 W/w 只」算，产出却按「每只都掉」
算，等于把单价压低了 `1/share` 倍。按两处 docstring 自己的口径
（「要拿一只平均得打死 W/w 只」），产出应当是单只的 `per_kill`。修完：

| 物品 | 修前 | 修后 | 倍数 |
|---|---|---|---|
| `wither_skeleton_skull` | 230.55 | **692.14** | 3.0x |
| `nether_star` | 662.01 | **2063.27** | 3.1x |
| `ghast_tear` | 29.80 | 30.42 | 1.02x |
| `prismarine_shard` | 75.89 | 75.89 | 1.0x |

`prismarine_shard` 一字不差正好说明修正只影响 `share < 1` 的来源：
海底神殿里守卫者占 100%，`kills = 1`，两种写法等价。
