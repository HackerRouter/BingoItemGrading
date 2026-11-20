"""补充的游戏数据：代码里硬编码、本该来自数据的游戏事实与标定值。

**只有这一份**，所有层都从这里引用——动作图、来源索引、挖掘换算、统计导入
都读同一个数，不存在「同一个量两处各存一份」。

**编码依赖不进这里**：能力名（`capability:nether_access`）、`action_id` 前缀、
类别词汇表（`FAMILY_TYPES` / `LOOT_PREFIX_TYPES`）、构造表、TU 换算与评分档位
留在各自模块——那些改错了要跟着改代码，是不一样的东西。

按性质分区，调参时按主题找，别按字母找：

1. **玩家操作时间**：走到 + 交互的手工耗时，游戏里没有这个字段，只能标定；
2. **等待与节奏**：等游戏推进（刷怪、袭击波次、Boss 阶段、孵化与成长），不是操作；
3. **种植**：种子换作物、等它长熟；自然生长与骨粉催熟两条口径；
4. **游戏机制**：代码写死的规则，改它等于改游戏，不算调参；
5. **模型规模参数**：一次挖几个、一片资源多大——决定成本曲线的形状；
6. **结构事实**：门框块数、缺口均值这类来自模板的确定值；
7. **世界事实**：哪些方块算水、哪些矿石按群系过滤、各维度地表高度；
8. **方块与工序时长**：破坏一个方块、熔炼一次要多久（按方块/工序查表）；
9. **概率登记**：战利品表里查不到、只能手工登记的触发概率。

事实数据不许进这里的方式要区分：**世界测量值**（村庄箱数、村民数、掉落、
结构内容）读 `stats/<pack>/`，**版本事实**（配方、交易）读上游 `facts/`。
缺数据时路线缺席并记缺口，不拿常量顶上——否则「估计值」会静默混进数据来源里。
第六、七类是例外：它们是查出来的确定值，放这里只是与标定值区分开。
"""

from __future__ import annotations

# =====================================================================
# 一、玩家操作时间
# =====================================================================

# 开一个箱子：走近 + 打开 + 扫一眼物品栏。
CHEST_SECONDS = 2.0

# 一次交易的手工操作时间。走到村民、开界面、点几下的摊薄成本相对材料
# 获取可以忽略，按 0 计（以前给 2 秒属于过度细节）。
TRADE_SECONDS = 0.0

# 在村庄里找到一个干草块堆：亮黄色、视觉明显，主要成本是走过去。
HAY_FIND_SECONDS = 2.0

# 击杀一只近战怪：走近、它扑一下、几下打完、拾取掉落。
# 远程怪（骷髅、烈焰人）需要保持距离，实操更慢，这里按近战口径统一。
KILL_SECONDS = 3.0

# 刷扫一个可疑方块：刷子刷完约 1 秒，加走近与判断位置。
SUSPICIOUS_SECONDS = 3.0

# 一次合成的手工操作：摆材料、点几下。走到合成台的跑图不算在这里，
# 合成台本身是 `once` 前置。
CRAFT_SECONDS_PER_STEP = 2.0

# 在结构里找到并走到「那一堆目标方块」的每块耗时。
# 红石线、镶金黑石这类分散在结构内部，不像干草块那样一眼看到，按 1 秒/块算。
STRUCTURE_FIND_SECONDS = 1.0

# 打碎一个陶罐：陶罐很脆，一下就没，成本在「在结构里找到它」。
POT_SECONDS = 2.0

# 用桶舀一只水生生物：下水、对准、右键。鱼会游动，比装水慢一点，
# 但不需要打死它，所以比 `KILL_SECONDS` 短。
SCOOP_SECONDS = 2.0

# 剪一次羊毛：走近、右键。羊不会跑，比击杀快得多。
SHEAR_SECONDS = 1.0

# 挤一次奶：走近、右键（拿桶）。
MILK_SECONDS = 1.0

# 取一瓶蜂蜜：拿玻璃瓶对蜜满的蜂巢右键。同一窝要重新酿才能再取，
# 所以一瓶 = 找一处蜂巢 + 取一次。
HONEY_SECONDS = 1.0

# 用斧头刮一次蜡 / 刮一次氧化层：对着方块右键，有 `cooldown` 但很短。
# 一次只作用一格，`damage_per_use = 1`（见 `facts/block_transform.jsonl`）。
WAX_OFF_SECONDS = 0.3

# 手持物品使用一次就换成另一个物品：空地图右键当场生成已填充地图（不需要
# 跑到未记录区块），书写并签名同理。成本就是一次右键，不叠行程。
ITEM_CONVERT_SECONDS = 1.0

# 铁匠台三级的降级链：anvil → chipped_anvil → damaged_anvil。
# 每次使用（修理/重命名/附魔合成）有 12% 概率掉一级，与使用类型无关；
# 所以「用到掉一级」的期望次数是 1/0.12 ≈ 8.33 次。
ANVIL_STAGES: tuple[str, ...] = (
    "minecraft:anvil",
    "minecraft:chipped_anvil",
    "minecraft:damaged_anvil",
)
ANVIL_DEGRADE_CHANCE = 0.12

# 一次铁砧操作：把要修的东西放上去、选中、点确认。
ANVIL_USE_SECONDS = 2.0

# 眼眸花随昼夜开合（`open_eyeblossom` / `closed_eyeblossom`）。一个完整昼夜
# 24000 tick = 20 分钟，白天夜晚各一半；玩家随时到，等它睁开平均要等半个
# 昼夜。降下去的那一半不用算：只要等到天黑，花自己会开。
EYEBLOSSOM_WAIT_SECONDS = 300.0

# 放下一个方块：对准、右键。比按住 Shift 搭桥快得多。
PLACE_SECONDS = 0.3

# 钓一次鱼：抛竿、等咬钩、收线。Minecraft 的等待是 5–30 秒随机，
# 期望约 17 秒，加上收线与重抛，取 20 秒。
FISH_SECONDS = 20.0

# 猪灵以物易物一次：走到猪灵、扔金锭、等它捡起并扔回物品、走过去捡。
BARTER_SECONDS = 4.0

# 收一份英雄赠礼：村民走过来扔东西，几乎是瞬时的，只算走过去捡。
GIFT_SECONDS = 1.0

# 垒门框 + 点火 + 跨进去：摆 10 块黑曜石（或补 4 块缺口）、打火、过门。
# 不含「先造打火石」——那是物品来源的事，由构造的输入引进来。
PORTAL_BUILD_SECONDS = 3.2

# =====================================================================
# 二、等待与节奏
# =====================================================================

# 刷怪笼每刷一只的等待。Minecraft 的延迟是 200–800 tick（10–40 秒），
# 取 15 秒当期望；玩家可以用水流/地形把怪堆起来，所以这是上限而非下限。
SPAWNER_WAIT_SECONDS = 15.0

# 袭击每一波之间的间隙：上一波清干净、下一波在村外刷出来、玩家跑过去。
# 波次本身由刷怪表给出（overworld 袭击 7 波），这里只补「等下一波出现」的时间。
RAID_WAVE_SECONDS = 15.0

# 打赢凋灵：召唤后它先蓄力无敌，然后两阶段打。有铁装与弓箭的话约 1–2 分钟；
# 这里取 60 秒当期望，不含「打输了重来」。
WITHER_FIGHT_SECONDS = 60.0

# 打赢一条末影龙：不带速通手法（不拆床、不利用龙椅瞬时击杀），按正常
# 「拆水晶 → 等落地 → 射/近战」算，约 20 分钟。取 1200 秒。
# 它唯一的用途是出龙蛋——龙息、鞘翅都不需要打死龙。
DRAGON_FIGHT_SECONDS = 1200.0

# 一个游戏日（白天 10 分钟 + 夜晚 10 分钟）。两处用到它：
#
# - **猫的晨间礼物**：只有「玩家睡觉后」的一次抽奖机会，所以周期是一整天。
#   多人服不会一起睡（一天一次）；单人能靠早睡快一点，但晚上还要打怪，
#   做不到「13 分钟睡一觉」，按 20 分钟计。
# - **幻翼刷新**：玩家连续 3 天没睡之后，才开始在夜里刷。
SECONDS_PER_GAME_DAY = 1200.0

# 猫送礼的周期：一个游戏日一次抽奖。
CAT_GIFT_SECONDS = SECONDS_PER_GAME_DAY

# 幻翼开始刷新前，玩家要连续不睡几个游戏日（vanilla 是第 3 天开始）。
PHANTOM_DAYS_WITHOUT_SLEEP = 3

# 接龙息：进末地后等末影龙飞过来喷一轮、拿瓶子接几瓶。
# 不需要打死它——龙息是它喷的火球落地后的效果，站着接就行。
DRAGON_BREATH_SECONDS = 30.0

# 自然刷怪「等一只」的周期。
#
# 刷怪笼有确定的 200–800 tick，自然刷怪没有：它受刷怪上限（mobcap）、
# 光照、玩家距离共同影响。这里取 5 秒当**近似**——mobcap 没满时下界荒地
# 平均 1–2 秒就能出一只，满了之后要杀一只才补一只。
#
# **这是全仓唯一一个「没有数据支撑、只能拍」的时间常量**，所以只用在
# 「群系刷怪」这条退路上（结构刷怪有玩家在场、用 `SPAWNER_WAIT_SECONDS`，
# 那不适用）。
#
# 方向在两种玩法下**相反**，用的人要自己判断落在哪一边：
# - **蹲点刷**（站在河边/下界荒地等，刷怪上限满了就杀）：真实约 1–2 秒/只，
#   取 5 秒会高估成本，偏**保守**（`_biome_mob_weighted` 的 label 写的是
#   「等刷怪」，按这个语义读）；
# - **跑图顺路**（一边赶路一边打）：可能十几秒才碰到一只，取 5 秒偏**乐观**。
#
# 低掉落率的来源对它最敏感：`trident` 走溺尸要打 1158 只怪，
# 5 秒/只给 1324 TU，1 秒/只给 662 TU，差一倍。
NATURAL_SPAWN_SECONDS = 5.0

# 海龟蛋孵化：3 个孵化阶段，**由随机刻推进**。Wiki 给的结论是「平均 4.5 个
# 游戏日」，一个游戏日 20 分钟，即 5400 秒。这里直接用这个期望值，不去解随机刻：
#
# - 每个游戏日第 21061–21904 刻（约 03:00–04:00）随机刻**必定**推进一个阶段；
# - 其他时刻的随机刻只有 0.2% 概率推进；
# - 随机刻本身是「每子区块每刻抽 3 格」，与方块在哪里、周围有多少随机刻方块
#   都有关，解析解只会把误差换成另一种形式。常量就是 wiki 的期望值。
TURTLE_EGG_HATCH_SECONDS = 5400.0

# 幼年海龟长大：20 分钟（`Age` 从 −24000 每刻 +1）。
#
# **这条不是随机刻**：成长走实体 tick，与方块随机刻无关（喂海草每次减少约
# 10% 剩余时间，那是加速手段，不作为基准）。所以孵化和成长是两段独立等待，
# 加起来才是「一颗蛋变成一格鳞甲」的时间。
TURTLE_GROW_SECONDS = 1200.0

# 嗅探兽：蛋孵出幼兽、幼兽长成成年兽，两段都不是随机刻。
#
# - 孵化：Wiki 给的是「通常约 20 分钟」（苔藓块上约 10 分钟，那是玩家加速手段，
#   不作为基准）；
# - 成长：幼兽需 **40 分钟** 才成年，与幼年海龟那个 20 分钟一样是实体 tick，
#   不是方块随机刻；
# - **只有成年兽才刨挖**，所以拿到第一颗古代种子要把这两段都等完。
SNIFFER_EGG_HATCH_SECONDS = 1200.0
SNIFFER_GROW_SECONDS = 2400.0

# 成年嗅探兽刨挖一次的间隔：每刨一次后冷却 9600 游戏刻（8 分钟），
# 冷却期间在接下来的 20 次嗅探里也会跳过这个方块。嗅探→走过去→刨土本身
# 只有十几秒，所以单次成本几乎完全由这个冷却决定。
SNIFFER_DIG_COOLDOWN_SECONDS = 480.0

# 成年鸡每 5–10 分钟下一个蛋（`EggLayTime` 重置到 6000–12000 刻），取期望 9000 刻。
# 鸡骑士里的鸡不下蛋、幼年鸡也不下蛋，所以前置是「一只普通成年鸡」。
# **不同变种下不同颜色的蛋**（温带白蛋 / 热带棕蛋 / 寒带蓝蛋）——变种由群系定，
# 想要哪种就去对应群系养，所以三种蛋各自按 1 个/次算。
CHICKEN_EGG_SECONDS = 450.0

# =====================================================================
# 三、种植
# =====================================================================
#
# 本项目的种植模型**不含耕地**（拿到种子直接种），也不算光照、湿度、
# 成片种植的加速。只保留两件事：种子换成作物、等它长熟。
#
# 作物方块 → 种子。作物方块自己的战利品表给出「一株收多少」
# （`loot_per_chest_all(blocks/<crop>)`），这里只补「用什么种」。
CROP_SEEDS: dict[str, str] = {
    "minecraft:torchflower": "minecraft:torchflower_seeds",
    "minecraft:torchflower_crop": "minecraft:torchflower_seeds",
    "minecraft:pitcher_plant": "minecraft:pitcher_pod",
    "minecraft:pitcher_crop": "minecraft:pitcher_pod",
    "minecraft:wheat": "minecraft:wheat_seeds",
    "minecraft:carrots": "minecraft:carrot",
    "minecraft:potatoes": "minecraft:potato",
    "minecraft:beetroots": "minecraft:beetroot_seeds",
}

# 每个作物方块成熟需要几个阶段（方块状态 `age` 的上限）。
#
# 前五个已用上游战利品表**核对过**：`match_block` 里写的 `state.age` 就是成熟值
# （`beetroots` 3、`carrots` 7、`potatoes` 7、`pitcher_crop` 4、`wheat` 7）。
# 火把花的战利品表不带 age 条件，按方块定义 `maxAge=1`。
CROP_MAX_AGE: dict[str, int] = {
    "minecraft:wheat": 7,
    "minecraft:carrots": 7,
    "minecraft:potatoes": 7,
    "minecraft:beetroots": 3,
    "minecraft:torchflower": 1,
    "minecraft:torchflower_crop": 1,
    "minecraft:pitcher_plant": 4,
    "minecraft:pitcher_crop": 4,
}

# ---------------------------------------------------------------- 随机刻机制
#
# 作物自然生长的时间**不是拍的**，它由随机刻机制完全决定：
#
# 1. 每个子区块（16³ = 4096 格）每 tick 抽 `RANDOM_TICK_SPEED` 次，
#    每次在 4096 格里均匀选一格 → 某一格被抽中的期望间隔
#    = 4096 / 3 tick ≈ 68.27 秒；
# 2. 抽中后按 `nextInt((int)(25 / speed) + 1) == 0` 推进一个阶段，
#    `speed` 是 `getGrowthSpeed`：3×3 全是湿润耕地给
#    `1 + 3（中心格 moisture>0）+ 8×(3/4) = 10`，
#    于是 `(int)(25/10) + 1 = 3` → 每次抽中 **1/3** 概率推进。
#
# 合起来每阶段期望 3 × 68.27 ≈ **204.8 秒**，小麦类 7 阶段 ≈ 23.9 分钟。
# `tools/sim_crop_growth.py` 用 Monte Carlo 模拟同一机制：1/3/4/7 阶段分别得
# 204/615/822/1442 秒，与解析值逐项对得上。
#
# **这是最快情形**：相邻有同种作物时 `speed` 减半（分母变 5，每阶段约 341 秒），
# 大片农田还会摊薄随机刻。所以自然路径给出的是下界，骨粉路径才是实际常用路线。
RANDOM_TICK_SPEED = 3
SUBSECTION_VOLUME = 16 * 16 * 16
TICKS_PER_SECOND = 20
CROP_GROWTH_CHECK_DIVISOR = 3


def crop_grow_seconds(crop: str) -> float | None:
    """某作物方块在**最佳条件**下长熟要几秒。`None` 表示不是已知作物。"""
    stages = CROP_MAX_AGE.get(crop)
    if stages is None:
        return None
    per_stage = (
        CROP_GROWTH_CHECK_DIVISOR
        * SUBSECTION_VOLUME
        / RANDOM_TICK_SPEED
        / TICKS_PER_SECOND
    )
    return stages * per_stage


# ---------------------------------------------------------------- 铜氧化
#
# 同样是随机刻机制（wiki「氧化 § 机制」）：每个随机刻有 `64/1125` 概率进入
# 「预氧化」，然后若周围（曼哈顿距离 ≤ 4）没有氧化程度更低的铜方块，
# 按 `m(b+1)²/(a+1)²` 氧化到下一级——`a` 是周围铜方块数、`b` 是其中更锈的，
# 未氧化方块 `m=0.75`，其余 `m=1`。
#
# 取「孤立单块」（`a=b=0`，wiki 说的最快情形）：
# - 阶段 1（未氧化→斑驳）：`1/(64/1125 × 0.75)` = 23.4375 次随机刻 → **1600 秒**
# - 阶段 2/3：`1/(64/1125)` = 17.578 次 → **1200 秒**
#
# 也就是从新铜块到全氧化约 67 分钟。被未氧化铜包围时 `(b+1)²/(a+1)²` 会把它
# 压到 1/(a+1)²，慢得没有实用意义——所以「放一块等它锈」是唯一现实路线。
COPPER_OXIDIZE_TICK_CHANCE = 64.0 / 1125.0
COPPER_FIRST_STAGE_FACTOR = 0.75


def copper_oxidize_seconds(stage: int) -> float:
    """铜氧化第 `stage` 级（1 = 未氧化→斑驳）的期望秒数，孤立单块。"""
    factor = COPPER_FIRST_STAGE_FACTOR if stage <= 1 else 1.0
    random_ticks = 1.0 / (COPPER_OXIDIZE_TICK_CHANCE * factor)
    per_tick = SUBSECTION_VOLUME / RANDOM_TICK_SPEED / TICKS_PER_SECOND
    return random_ticks * per_tick

# 骨粉催熟：wiki「骨粉 § 催熟」给的是**每次使用推进几个阶段**：
# - 小麦 / 胡萝卜 / 马铃薯：2–5 个阶段（期望 3.5）→ 7 个阶段约 2 次；
# - 瓶子草植株、火把花植株：每次只推进 1 个阶段 → 瓶子草 4 次、火把花 1 次。
#
# 甜菜根：查代码确认**平均 4 次**（它的阶段推进与小麦类不同，wiki 没给能直接用的
# 合并口径，按代码里的实际推进量取均值）。
#
# 所以骨粉路径的成本 = 用量 × 每次使用耗时 + 收割，与上面的自然生长无关。
BONEMEAL_USES: dict[str, int] = {
    "minecraft:torchflower": 1,
    "minecraft:torchflower_crop": 1,
    "minecraft:pitcher_plant": 4,
    "minecraft:pitcher_crop": 4,
    "minecraft:wheat": 2,
    "minecraft:carrots": 2,
    "minecraft:potatoes": 2,
    "minecraft:beetroots": 4,
}

# 使用一次骨粉的操作时间（对准方块、用掉、看它跳阶段）。
BONEMEAL_SECONDS_PER_USE = 1.0

# 收割一株：破坏方块本身只要 0.05 秒，剩下是走过去、捡起掉落物。
CROP_HARVEST_SECONDS = 1.0

# =====================================================================
# 四、游戏机制（改它就是改规则）
# =====================================================================

# 浇铸黑曜石：倒一桶岩浆到水边等它冷却。
CAST_SECONDS_PER_BLOCK = 0.5

# 在岩浆边装一桶：走近、右键、等流体回稳。
BUCKET_FILL_SECONDS = 0.5

# 村民升级所需的**累计**经验。下标就是等级：1 级 0、2 级 10、3 级 70、4 级 150、5 级 250。
# 这是 vanilla 机制（`Villager` 的等级经验表），不是待标定的行为参数——
# 和 `CAST_SECONDS_PER_BLOCK` 同一类：改它就是改游戏规则，不是调参。
# 每次交易给多少经验由数据给（`trade_offer` 的 `offer["xp"]`）。
VILLAGER_LEVEL_XP = (0.0, 0.0, 10.0, 70.0, 150.0, 250.0)

# 树脂农场：夜里打一只被 creaking heart 护着的嘎枝，heart 会在相连的苍白橡木
# 原木侧面长出树脂团方块。
#
# 这些是**游戏机制**，不是待标定的行为参数：
# - 每轮生成 2–3 块，取期望 2.5；
# - 两轮之间 5 秒冷却；
# - 树脂方块硬度 0，任何工具瞬间挖（约 0.05 秒/块）；
# - 嘎枝免疫伤害，这一下只是为了触发长树脂。
#
# 等待入夜**不计成本**：Bingo 里「算好时间天黑再过去」是顺带的事。
RESIN_PER_TRIGGER = 2.5
RESIN_COOLDOWN_SECONDS = 5.0
RESIN_BREAK_SECONDS = 0.05
RESIN_HIT_SECONDS = 0.5

# 玩家水平移动速度（格/秒）。wiki 与实测一致。
# Bingo 玩家全程疾跑，所以「1 TU 能跑多远」由 `units.RUN_BLOCKS_PER_TU` 按这个
# 速度派生；改移动速度而不是改 TU 定义时，改的就是这两个数。
WALK_BLOCKS_PER_SECOND = 4.317
SPRINT_BLOCKS_PER_SECOND = 5.612
# 游泳速度。`units.UNDERWATER_MOVE_FACTOR` 不是由它算出来的（那是模型乘数），
# 这个数只在注释里用来说明「水下慢多少」。
SWIM_BLOCKS_PER_SECOND = 3.92

# =====================================================================
# 五、模型规模参数（决定成本曲线的形状）
# =====================================================================

# 一个紫水晶洞里有几块 `budding_amethyst`。
#
# 这个数是「每洞规模」，**唯一一个没法从采样里消掉的量**：采样只给「每区块密度」，
# 而 `budding / 每洞块数 = 洞的密度`、`cluster / 洞密度 = 每洞成熟簇数`，
# 两个方程三个未知。给其中任何一个（每洞 budding 数 或 洞密度）都能闭合。
#
# 取 30 的依据：wiki 的洞生成率 1/24 区块 × 30 ≈ 每区块 1.25 块 budding，
# 与快照实测 `budding_amethyst` **1.2616/区块** 吻合到 1% 以内。
# **数据包只调生成率、不调洞内部结构**，而生成率已经被采样吃进去了，
# 所以这个常数不受数据包影响。若哪天数据包改了洞的尺寸，改这一个数即可。
GEODE_BUDDING = 30.0

# 一片岩浆湖大概能装几桶。岩浆成片，一片通常几十块（用户观察「明显大于 10」）。
LAVA_BLOCKS_PER_PATCH = 50.0

# 一次浇铸产出几块黑曜石：一次往返岩浆湖能带回的桶数上限。
# 岩浆源遇水只把**那一格**变成黑曜石，所以批量 = 桶数。
CAST_BATCH = 10.0

# 挖矿道的默认截面（1 宽 × 2 高，标准人身高）。
# 截面越大，单位长度扫过的方块越多，但每格要挖的方块也越多。
DEFAULT_SWATH = 2

# 判定「密度估计够用」所需的方块数。
#
# 判据用方块数而不是区块数：密度是 `方块数 / 等效区块数`，其相对误差由计数
# 主导（1/√n），n 是数到的方块数。区块数只影响空间聚类带来的额外方差，
# 不该把一个数到 1800 块的群系判成「样本不足」。
#
# 200 与上游 `minOreSamples` 的默认值一致，两边口径可以对齐核对。
MIN_DENSITY_BLOCKS = 200

# 地下移动的倍率：要插火把、避怪、走矿道，比地表慢。
UNDERGROUND_MOVE_FACTOR = 2.0

# 水下移动的倍率。
#
# 拆成两部分：
# - **速度本身**只慢一点：游泳约 3.92 m/s，对疾跑 5.612 m/s 是 1.43 倍
#   （对行走 4.317 m/s 只有 1.10 倍）。所以单看移动速度，水下远没有那么贵。
# - **氧气与视野**再补一倍左右：水下不换气只能待几十秒，得频繁上浮、或用门/
#   气泡柱/海带造气室；视野受限要贴着结构摸，竖直方向也慢。
#
# 两者相乘 ≈ 2.0。**不按「氧气量 ÷ 耗氧速度」硬算**：气室、水下呼吸药水、
# 海龟壳、气泡柱都能把停留时间拉长几倍，而这些是玩家的选择而不是环境常量，
# 硬算会把「带药水」和「裸潜」混成一个数。乘数至少能保证排序正确。
#
# 与地下的 2.0 同量级但成因不同：水下是速度加氧气，地下是速度加绕路。
# 地下比水下更贵的那部分由竖井（`descend_cost`）单独承担，不叠在这里。
UNDERWATER_MOVE_FACTOR = 2.0

# 判定「这个结构在水下」的水占比阈值。
#
# 实测 `blocks_per_start` 的水占比在两个世界里分得很开：
# `monument` 0.81、`shipwreck` 0.61、`ocean_ruin_*` 0.56–0.63、`ruined_portal_ocean` 0.64
# 对 `shipwreck_beached` 0.31（搁浅在沙滩上）、`mineshaft_mesa` 0.37、其余 < 0.08。
# 0.5 落在中间的空档里，不需要逐条登记结构名。
UNDERWATER_WATER_SHARE = 0.5

# =====================================================================
# 六、结构事实（来自模板或数据包的确定值）
# =====================================================================

# 下界门框要几块黑曜石：上下各 2 + 左右各 3，四角不需要。
# 这是 vanilla 的合成规则，不是可调参数。
FULL_FRAME = 10.0

# 末地传送门要几个末影之眼：框架 12 格，四角不需要。
END_FRAME_EYES = 12.0

# 废弃传送门平均还缺几块门框黑曜石：13 个模板实测的等权均值
# （`templates.py` 在每种模板里找最像门框的窗口，缺口 1–7 块）。
# 拿不到模板数据时直接用它兜底。
PATCH_FRAME = 4.0

# 下界门的标准形状：内部 2×3；框架 = 上下各 2 横梁 + 左右各 3 立柱 = 10 块。
# 四角不需要，所以最小的门是 10 块黑曜石而不是 4×5 外圈的 14 块。
# `templates.FRAME_RING` 由这两个数推导，`tests/test_gamedata.py` 钉住它与 `FULL_FRAME` 一致。
PORTAL_INNER_WIDTH = 2
PORTAL_INNER_HEIGHT = 3
PORTAL_FRAME_WIDTH = PORTAL_INNER_WIDTH + 2
PORTAL_FRAME_HEIGHT = PORTAL_INNER_HEIGHT + 2

# =====================================================================
# 七、世界事实
# =====================================================================

# 判定「结构在水下」时算作水的方块。海草与海带是水下的强信号——
# 沉船与海底废墟的 `blocks_per_start` 里它们占相当比例。
WATER_BLOCKS = frozenset(
    {
        "minecraft:water",
        "minecraft:seagrass",
        "minecraft:tall_seagrass",
        "minecraft:kelp",
        "minecraft:kelp_plant",
        "minecraft:bubble_column",
    }
)

# 方块 → 它在 worldgen 采集器里被当成「成湖 feature」量过的主体。
# 有映射的资源按实测的湖间距定价（见 `CaseContext.lake_source`），
# 没有映射的才退回纵段散点口径。
#
# 目前只有岩浆：`lava-lakes.json` 量的是**地表**岩浆湖，地下岩浆没有
# 间距测量，所以下界的岩浆海不在表里（而且下界本身要先进去）。
LAVA_LAKE_SETS = {
    "minecraft:lava": "minecraft:surface_lava_lake",
}

# 能抓到鱼的群系。按 `biome_patch` 的 `area_fraction` 加权算「走到最近水域」的距离：
# 水域合计占 32.4% 的地表面积（河流 6.0%、海洋 7.4%、其余海 18.6%），
# 所以「找条河捞一条鱼」在 Bingo 里几乎不是成本——这条路线不该缺席。
FISH_WATER_BIOMES = frozenset(
    {
        "minecraft:river",
        "minecraft:frozen_river",
        "minecraft:ocean",
        "minecraft:deep_ocean",
        "minecraft:warm_ocean",
        "minecraft:lukewarm_ocean",
        "minecraft:deep_lukewarm_ocean",
        "minecraft:cold_ocean",
        "minecraft:deep_cold_ocean",
        "minecraft:frozen_ocean",
        "minecraft:deep_frozen_ocean",
        # 沼泽有大片水面，蛤蚊与热带鱼就在这里
        "minecraft:swamp",
        "minecraft:mangrove_swamp",
    }
)

# **真的按群系过滤生成**的矿石。只有这几种允许「专门跑去那个群系挖」。
#
# 依据是 `ore_density` 里各群系密度的离散度：19 种矿里只有这 4 种明显离群
# （最高/中位：绿宝石 180×、金 7.6×、深板岩绿宝石 5.9×、铜 2.8×），
# 其余 15 种在 54 个群系之间的差异都在 2 倍以内，那是采样方差 + 地形高度差，
# 不是「矿只在某些群系生成」。把那些也拿来挑最小值，等于系统性挑选采样噪声
# 的高端（winner's curse），还会得出「为了挖煤去冰刺之地」这种结论。
#
# 对应 vanilla 的生成规则：
# - `emerald_ore` / `deepslate_emerald_ore`：只在 `is_mountain` 标签的群系生成
# - `gold_ore`：恶地有额外的 `badlands_gold_ore` 层（y32–79），是全球之外的增量
# - `copper_ore`：溶洞有额外的 `dripstone_caves_copper_ore`（更大团簇）
#
# 不在这个集合里的矿石一律按「就地挖」定价（密度取所有群系合并采样）。
# 新增前先看 `ore_density` 的离散度，别凭印象加。
BIOME_SPECIFIC_ORES: frozenset[str] = frozenset(
    {
        "minecraft:emerald_ore",
        "minecraft:deepslate_emerald_ore",
        "minecraft:gold_ore",
        "minecraft:copper_ore",
    }
)

# 各维度的地表高度近似值，用于算「从地表到目标层的距离」。
#
# 主世界：恶地陶瓦层厚，地表比 70 高，但差 10 格以内，不单独建模。
# 下界：玩家从传送门进来通常在 y 40–70 的岩层中，取 50；再往下才是熔岩海（y 32）。
# 末地：主岛平台约 y 60–70。
SURFACE_Y_BY_DIMENSION: dict[str, int] = {
    "minecraft:overworld": 70,
    "minecraft:the_nether": 50,
    "minecraft:the_end": 64,
}

# 缺省地表高度。未知维度按主世界算。
SURFACE_Y = SURFACE_Y_BY_DIMENSION["minecraft:overworld"]

# 深板岩起始高度：y < 0 的围岩是深板岩，挖起来更硬。
DEEPSLATE_BELOW_Y = 0

# =====================================================================
# 八、方块与工序时长
# =====================================================================

# 破坏方块的时长不在这里手写——上游 `facts/mining.jsonl` 给了每个方块的
# `hardness` 与 `requires_correct_tool`，`mining_facts.py` 按下式计算：
#   `hardness × (1.5 正确工具 / 5.0 错误或徒手) / 工具速度`
# 下面两条是**项目特化口径**（不是游戏数据）：
#
# 1. 速度默认按**石质**工具：前置虽然是木制（自举，见 `mining_facts` docstring），
#    但玩家拿到石头就会换石镐，按木镐速度算会系统性高估早期方块。
# 2. **地下开矿模型**（矿道 / 洞穴）按**铁质**工具：那套模型假设玩家已进入铁器阶段。
MINING_SPEED_MATERIAL = "stone"
UNDERGROUND_MINING_MATERIAL = "iron"

# 破坏方块的默认类型（主世界）。挖矿道挖到的大多是围岩，不是目标矿。
DEFAULT_BLOCK = "stone"

# 熔炼一次耗时（秒）。熔炉 200 tick，高炉 100 tick；按熔炉计，
# 因为高炉本身要先做出来（3 铁锭 + 5 铁锭 + 3 平滑石），对单个金锭不划算。
SMELT_SECONDS = 10.0

# 一份燃料能炼几次。煤炭 = 1600 tick = 8 次。
SMELTS_PER_FUEL = 8

# =====================================================================
# 九、概率登记（战利品表算不出、只能手工登记）
# =====================================================================

# 数值已尽可能由战利品表推导（ADR 0027），这里只留「数据包里查不到」的几类：
# 树叶掉木棍、女巫掉落、僵尸额外掉落、装备掉落。
# 键是 `(物品, 来源类别, 对象)`；未登记的来源按确定性处理。
# `sources/knowledge.py::probabilities_table()` 把它变成 `Probabilities` 对象。
PROBABILITY_ROWS: tuple[tuple[str, str, str, float, str], ...] = (
    ("minecraft:stick", "block_drop", "minecraft:oak_leaves", 0.05, "橡树叶掉木棍 5%，其他树种 2%"),
    ("minecraft:stick", "block_drop", "minecraft:birch_leaves", 0.02, "桦树叶掉木棍 2%"),
    ("minecraft:stick", "block_drop", "minecraft:spruce_leaves", 0.02, "云杉树叶掉木棍 2%"),
    ("minecraft:redstone", "mob_drop", "minecraft:witch", 0.125, "女巫掉红石 1–4 个，掉落概率 12.5%"),
    ("minecraft:iron_ingot", "mob_drop", "minecraft:zombie", 0.025, "僵尸额外掉落铁锭 2.5%"),
    ("minecraft:iron_ingot", "mob_drop", "minecraft:husk", 0.025, "厄壳额外掉落铁锭 2.5%"),
    ("minecraft:glowstone_dust", "mob_drop", "minecraft:witch", 0.125, "女巫掉萤石粉 12.5%"),
    (
        "minecraft:trident",
        "mob_drop",
        "minecraft:drowned",
        0.005313,
        "濡尸 6.25% 生成时 mainhand 手持三叉戟 × 8.5% 死亡掉落 = 0.531%，平均 188 只出一把",
    ),
)
