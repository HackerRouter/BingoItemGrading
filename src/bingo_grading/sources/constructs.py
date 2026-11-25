"""构造：不是物品、但能用「输入 → 输出」表达的状态。

与合成配方的区别只有两点：

1. **产出可以是 `capability:`**——「能站在下界里」「手里有火」不是物品，
   但它们照样有来源、有价格，理应进同一张供给曲线。
2. **输入可以是占位符**——`capability:lava_access@*` 表示「任意一处岩浆湖」，
   每段岩浆是一条独立来源，由 `CaseContext.patch_sources` 展开。

下界门按这个模型拆成两条**并列构造**，让引擎自己比：

```text
capability:nether_access
├ portal:full_frame      ← obsidian ×10 + igniter        （从零垒满框）
└ portal:patch_ruined    ← capability:ruined_portals ×1
                            + obsidian ×4 + igniter      （废弃传送门已有 6 块，补缺口）
```

「门框模板缺口」因此不再是一个手写的 overhead 常数：它就是
`portal:patch_ruined` 比 `portal:full_frame` 少要的 6 块黑曜石，
而缺口那股「平均还缺 4 块」来自 13 个废弃传送门模板的实测。

黑曜石的来源则完全交给自动入口：挖矿、末地城箱子、废弃传送门方块
（`structure_content.blocks_per_start`），再加上这里声明的**浇铸**：

```text
minecraft:obsidian
└ cast:obsidian@<y>     ← capability:lava_access@<y> + capability:bucket + lava ×10
```

点火物也是普通物品来源，递归定价：

```text
capability:igniter
├ igniter:flint_and_steel  ← minecraft:flint_and_steel   （燧石 + 铁锭）
└ igniter:fire_charge      ← minecraft:fire_charge       （火药 + 烈焰粉 + 煤）
```

**火焰弹那条路会绕回下界**（烈焰粉 ← 烈焰棒 ← 烈焰人 ← 要去下界），
所以它不能当第一座门的点火物。这个环由 `build()` 的路径栈截断、
由供给曲线的预算分层保证「算门的时候那条曲线还没出生」。
"""

from __future__ import annotations

from dataclasses import dataclass

from bingo_grading import gamedata
from bingo_grading.plan.actions import MODE_ONCE, MODE_PER_USE

NETHER_ACCESS = "capability:nether_access"
THE_END_ACCESS = "capability:the_end_access"
IGNITER = "capability:igniter"
LAVA_ACCESS = "capability:lava_access"
# 走到一处废弃传送门（门框已经在那里，只是缺几块）。
RUINED_FRAME = "capability:minecraft:ruined_portals"
# 走到一处要塞（末地传送门框架就在里面）。
STRONGHOLD = "capability:minecraft:strongholds"

OBSIDIAN = "minecraft:obsidian"
LAVA = "minecraft:lava"
BUCKET = "capability:bucket"
# 铁桶本体：状态 `capability:bucket` 由它包装而来（造一次能反复用）。
BUCKET_ITEM = "minecraft:bucket"
FLINT_AND_STEEL = "minecraft:flint_and_steel"
FIRE_CHARGE = "minecraft:fire_charge"
ENDER_EYE = "minecraft:ender_eye"

# 门框/框架的块数、浇铸批量、摆门耗时都是**游戏数据**，数值归
# `bingo_grading/gamedata.py`（那里按主题分区）；这里只保留名字，供构造表按名引用。
END_FRAME_EYES = gamedata.END_FRAME_EYES
FULL_FRAME = gamedata.FULL_FRAME
PATCH_FRAME = gamedata.PATCH_FRAME
PORTAL_BUILD_SECONDS = gamedata.PORTAL_BUILD_SECONDS
CAST_BATCH = gamedata.CAST_BATCH


@dataclass(frozen=True)
class Construct:
    """一条「输入 → 产出」的构造。

    `inputs` 里的名字如果是 `...@*` 后缀，表示**占位符**：
    由调用方按 `CaseContext.patch_sources` 展开成每段一条来源。
    """

    id: str
    product: str
    amount: float
    inputs: tuple[tuple[str, float], ...]
    seconds: float
    label: str
    source: str = "construct"
    # 这些输入是**一次性状态**（进过一次末地、打完一场龙）：整个方案里只付一次，
    # 与 `Requirement` 的 `once` 同义。写在 `inputs` 里的名字才能标；未列出的仍按
    # `per_use` 计价（原料、消耗品）。
    once_inputs: tuple[str, ...] = ()
    # 「这个输入不许用哪几条来源」：`(输入物品, (来源前缀, ...))`。
    # 不是价格判断，而是**操作上做不到**：把 `Requirement.forbid` 带到构造表里。
    forbid: tuple[tuple[str, tuple[str, ...]], ...] = ()
    # 「这个输入不许用「不先拿到它们就拿不到」的来源」：`(输入物品, (物品, ...))`。
    # 自举约束：开门用的东西不能来自己经开好的门。见 `Requirement.forbid_needs`。
    forbid_needs: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def forbid_for(self, item: str) -> tuple[str, ...]:
        """某个输入禁用的来源前缀。"""
        for name, prefixes in self.forbid:
            if name == item:
                return prefixes
        return ()

    def forbid_needs_for(self, item: str) -> tuple[str, ...]:
        """某个输入的自举约束目标。"""
        for name, targets in self.forbid_needs:
            if name == item:
                return targets
        return ()

    def mode_for(self, item: str) -> str:
        """这个输入按 `once` 还是 `per_use` 计价。"""
        return MODE_ONCE if item in self.once_inputs else MODE_PER_USE


# 浇铸出来的黑曜石只能用来**从零垒整框**（挖坑、倒水、浇岩浆，一次成型）。
# 在废弃传送门已有的框架缺口上精确浇一块，操作难度完全是另一件事：
# 缺口旁边就是现成的框架方块，浇下去很容易连框一起挡、或者凝固在错的位置。
# 所以「补现成框架」只接受**现成的黑曜石**（开箱、挖矿），不接受浇铸。
CAST_SOURCES = ("cast:obsidian",)

# 开门用的东西不能来自己经开好的门。下界里也能拿到黑曜石（堡垒箱子、
# 猪灵交易、下界建筑），但那是先有门才拿得到的——用它给门框定价是循环。
LOCKED_BEHIND_NETHER = ((OBSIDIAN, (NETHER_ACCESS,)), (IGNITER, (NETHER_ACCESS,)))


NETHER_CONSTRUCTS: tuple[Construct, ...] = (
    Construct(
        id="portal:full_frame",
        product=NETHER_ACCESS,
        amount=1.0,
        inputs=((OBSIDIAN, FULL_FRAME), (IGNITER, 1.0)),
        seconds=PORTAL_BUILD_SECONDS,
        label="从零垒满 10 块黑曜石、点火、走进去",
        forbid_needs=LOCKED_BEHIND_NETHER,
    ),
    Construct(
        id="portal:patch_ruined",
        product=NETHER_ACCESS,
        amount=1.0,
        inputs=((RUINED_FRAME, 1.0), (OBSIDIAN, PATCH_FRAME), (IGNITER, 1.0)),
        seconds=PORTAL_BUILD_SECONDS,
        label="在废弃传送门上补缺口的黑曜石、点火、走进去",
        forbid=((OBSIDIAN, CAST_SOURCES),),
        forbid_needs=LOCKED_BEHIND_NETHER,
    ),
    Construct(
        id="igniter:flint_and_steel",
        product=IGNITER,
        amount=1.0,
        inputs=((FLINT_AND_STEEL, 1.0),),
        seconds=0.0,
        label="用打火石点火",
    ),
    Construct(
        id="igniter:fire_charge",
        product=IGNITER,
        amount=1.0,
        inputs=((FIRE_CHARGE, 1.0),),
        seconds=0.0,
        label="用火焰弹点火（要烈焰粉，会绕回下界）",
    ),
    # 铁桶是物品，但「手里有个桶」是状态：它在浇铸里被反复用（同一个桶来回装），
    # 所以下游按 `capability:bucket` 引用。这条把物品接成状态，成本 0。
    Construct(
        id="capability:bucket",
        product=BUCKET,
        amount=1.0,
        inputs=((BUCKET_ITEM, 1.0),),
        seconds=0.0,
        label="铁桶（可重复装流体）",
        source="game_rule",
    ),
)

NETHER_STAR = "minecraft:nether_star"
SOUL_SAND = "minecraft:soul_sand"
WITHER_SKULL = "minecraft:wither_skeleton_skull"
WITHER_ROSE = "minecraft:wither_rose"

# 凋灵玫瑰：凋灵杀死其他生物时，在尸体位置生成一朵。
#
# 它**不是挖出来的方块，也不是掉落物**：`blocks/wither_rose` 那张战利品表
# 只对已经存在的方块生效，而方块本身不自然生成，所以四条挖掘模型全部返回 0 密度。
#
# 实际玩法就是「把凋灵召唤到一窝生物里，让它一把炸死」。所以这一条与
# `wither:summon` 共用同一场战斗：同样的灵魂沙 + 3 个头骨 + 同样的战斗时长。
#
# `amount` 取 5.5（「5～6 朵」的中值）：一场能出几朵取决于**玩家提前聚了多少生物**，
# 而聚怪本身几乎不花时间（引一群僵尸/鸡到下界门边上）。取 1 是「只炸死一只」的下界，
# 会把成本高估五倍以上；「引好一群再召唤」才是常见打法。
WITHER_CONSTRUCTS: tuple[Construct, ...] = (
    Construct(
        id="wither:summon",
        product=NETHER_STAR,
        amount=1.0,
        inputs=((SOUL_SAND, 4.0), (WITHER_SKULL, 3.0)),
        seconds=gamedata.WITHER_FIGHT_SECONDS,
        label="灵魂沙摆 T 形、放 3 个凋灵骷髅头、召唤并击败凋灵",
        source="game_rule",
    ),
    Construct(
        id="wither:rose",
        product=WITHER_ROSE,
        amount=5.5,
        inputs=((SOUL_SAND, 4.0), (WITHER_SKULL, 3.0)),
        seconds=gamedata.WITHER_FIGHT_SECONDS,
        label="把凋灵召唤到生物群里，让它炸死它们并在倒地处留下凋灵玫瑰（一场 5～6 朵）",
        source="game_rule",
    ),
)

# 浇铸：岩浆源遇水变黑曜石。规则直接声明在这里（`transforms.toml` 已删除，
# 它从未进入生产路径）；这里只写「输入里有一段是成片资源，要按段展开」。
CASTING: Construct = Construct(
    id="cast:obsidian",
    product=OBSIDIAN,
    amount=CAST_BATCH,
    inputs=((f"{LAVA_ACCESS}@*", 1.0), (BUCKET, 1.0), (LAVA, CAST_BATCH)),
    seconds=0.0,
    label="倒岩浆浇成黑曜石（浇出来直接就是门框，不用挖）",
    source="game_rule:cast:obsidian",
)

LAVA_BUCKET = "minecraft:lava_bucket"

# 岩浆桶：拿铁桶去岩浆边舀一桶。
#
# 上游把它登记在 `code/fluid_buckets` 里，但那是「这个物品存在」的登记，
# `subject` 是 Item 注册代码路径（不是方块名），掉落侧产不出动作，所以补构造。
# 口径与校准动作 `bucket:lava@lake` 一致：1 份 `minecraft:lava` = 1 桶。
BUCKET_CONSTRUCTS: tuple[Construct, ...] = (
    Construct(
        id="bucket:lava_bucket",
        product=LAVA_BUCKET,
        amount=1.0,
        inputs=((BUCKET, 1.0), (LAVA, 1.0)),
        seconds=gamedata.BUCKET_FILL_SECONDS,
        label="拿铁桶舀一桶岩浆",
        source="game_rule",
    ),
)

ADULT_SNIFFER = "capability:adult_sniffer"
SNIFFER_EGG = "minecraft:sniffer_egg"

# 成年嗅探兽：蛋 → 幼兽（约 20 分钟）→ 成年（40 分钟），**幼兽不刨地**。
# 古代种子只能靠成年兽刨出来，所以这两段等待是拿种子绕不开的。
SNIFFER_CONSTRUCTS: tuple[Construct, ...] = (
    Construct(
        id="sniffer:adult",
        product=ADULT_SNIFFER,
        amount=1.0,
        inputs=((SNIFFER_EGG, 1.0),),
        seconds=gamedata.SNIFFER_EGG_HATCH_SECONDS + gamedata.SNIFFER_GROW_SECONDS,
        label="孵化嗅探兽蛋、等幼兽长成成年（幼兽不会刨地）",
        source="game_rule",
    ),
)

# 末地传送门：要塞里的 12 格框架 + 12 个末影之眼。
#
# 末影之眼本身是「末影珍珠 + 烈焰粉」，而烈焰粉只能从下界拿——所以去末地
# 必然先过下界。这条依赖链不是谁写死的，是构造表递归出来的：
#   the_end_access ← ender_eye ×12 + strongholds
#   ender_eye      ← ender_pearl + blaze_powder
#   blaze_powder   ← blaze_rod ← 下界要塞刷怪笼
ENDER_EYE = "minecraft:ender_eye"
ENDER_PEARL = "minecraft:ender_pearl"
GLASS_BOTTLE = "minecraft:glass_bottle"
DRAGON_BREATH = "minecraft:dragon_breath"
DRAGON_EGG = "minecraft:dragon_egg"
# 打死一场末影龙的产物：`dragon_egg` 与 `outer_end`（走折跃门）的公共前置。
DRAGON_SLAIN = "capability:dragon_slain"

# 末地外岛（末地城、末地船）。进了末地只到主岛，外岛在约 1000 格虚空之外。
# 两条到达方式各自是一条构造，求解器对同一产物取小；`end:gateway` 顺带出龙蛋。
OUTER_END = "capability:outer_end"

# 哪些结构集合在外岛。目前只有末地城（末地船是它的一部分，不单列集合）。
OUTER_END_SETS = frozenset({"minecraft:end_cities"})

END_CONSTRUCTS: tuple[Construct, ...] = (
    Construct(
        id="end:portal",
        product=THE_END_ACCESS,
        amount=1.0,
        inputs=((STRONGHOLD, 1.0), (ENDER_EYE, END_FRAME_EYES)),
        seconds=PORTAL_BUILD_SECONDS,
        label="在要塞的传送门框架上嵌满 12 个末影之眼、跳进去",
        source="game_rule",
    ),
    # 杀龙：摆 4 个水晶复活、清掉柱上水晶、把末影龙打死。**不含**捡蛋。
    #
    # 单独建成一个节点，是因为它是「要龙蛋」和「走折跃门去外岛」的**公共前置**：
    # 同一行 Bingo 里两件都要时，这笔只该付一次。拆开之前两条构造各自内联 365 s，
    # 组合计价会把同一场龙战算两遍。
    #
    # `the_end_access` 是 `once`（进一次末地，打几场都在里面），见 `Construct.once_inputs`。
    Construct(
        id="dragon:kill",
        product=DRAGON_SLAIN,
        amount=1.0,
        inputs=((THE_END_ACCESS, 1.0),),
        once_inputs=(THE_END_ACCESS,),
        seconds=gamedata.DRAGON_SLAIN_SECONDS,
        label=(
            "进末地摆 4 个水晶复活、清掉柱上水晶、打死末影龙"
            f"（实测准备 {gamedata.DRAGON_PREP_SECONDS:g} + "
            f"龙战 {gamedata.DRAGON_FIGHT_SECONDS:g} 秒）"
        ),
        source="game_rule",
    ),
    # 龙蛋：末影龙死后在返回传送门上方生成，**不是掉落物**。所以成本 = 前面
    # 那场龙战 + 把蛋取走（破蛋 + 拾取，实测 23.1 s）。
    #
    # 23.1 s 的窗口本身已含「破蛋 + 拾取」，不再叠加 `PLACE_SECONDS`。
    Construct(
        id="dragon:egg",
        product=DRAGON_EGG,
        amount=1.0,
        inputs=((DRAGON_SLAIN, 1.0),),
        once_inputs=(DRAGON_SLAIN,),
        seconds=gamedata.DRAGON_EGG_SECONDS,
        label="龙死后在返回传送门上方生成龙蛋，破蛋并取走（实测约 23 秒）",
        source="game_rule",
    ),
    # 龙息不需要打末影龙：等它喷一轮，拿瓶子接就行。所以成本几乎等于
    # 「进得去末地」，而不是「打赢一场龙战」。
    #
    # 鞘翅不能照此推论：它在外岛末地城，那里离主岛约 1000 格虚空。这一段由
    # `capability:outer_end` 单独承担（下面两条构造），龙息不依赖它。
    Construct(
        id="end:dragon_breath",
        product=DRAGON_BREATH,
        amount=1.0,
        inputs=((THE_END_ACCESS, 1.0), (GLASS_BOTTLE, 1.0)),
        seconds=gamedata.DRAGON_BREATH_SECONDS,
        label="进末地后等末影龙喷火球、用玻璃瓶接龙息（不用打死它）",
        source="game_rule",
    ),
    # 到达外岛（末地城）的两条路。模型对同一产物取小，两条都建，不手工挑便宜的。
    #
    # 路径 1：打完龙走折跃门。折跃门在龙死后生成于主岛边缘，代价 = 打死龙
    # （与龙蛋共用 `dragon:kill`）+ 走到门 + 穿过去。
    #
    # **不消耗末影珍珠**：门是个 1 格高的方块，走进去就传送。够不到时压身位
    # （活板门 / 半砖）或坐船、坐矿车都能蹭过去，这些手法的差别只有几秒，
    # 也都不要材料——按「走过去」建模，不引入一个会被无数替代方案绕开的耗材。
    #
    # 这里只付 `END_GATEWAY_SECONDS`（走到门 24 s + 穿门 1 s）：龙战那 341.9 s
    # 由 `dragon:kill` 承担。也不含「破蛋 + 拾取」那 23.1 s——那是龙蛋自己的
    # 最后一步，只为去外岛的人不必付。
    Construct(
        id="end:gateway",
        product=OUTER_END,
        amount=1.0,
        inputs=((DRAGON_SLAIN, 1.0),),
        once_inputs=(DRAGON_SLAIN,),
        seconds=gamedata.END_GATEWAY_SECONDS,
        label="打完末影龙（与龙蛋共用那场战斗），走到主岛边缘的折跃门穿到外岛",
        source="game_rule",
    ),
    # 路径 2：不打龙，自己搭桥横渡约 1000 格虚空。
    #
    # 只算「边后退边放」的移动，**不计挖方块**：1000 格约 16 组（1025 块），
    # 玩家背包背得下，而且会自带木头/泥土这类好挖的，不会临时去挖末地石。
    Construct(
        id="end:bridge",
        product=OUTER_END,
        amount=1.0,
        inputs=((THE_END_ACCESS, 1.0),),
        seconds=gamedata.END_OUTER_GAP_BLOCKS / gamedata.END_BRIDGE_BLOCKS_PER_SECOND,
        label="从主岛边缘搭桥横渡约 1000 格虚空到外岛（不打死龙）",
        source="game_rule",
    ),
)

CONSTRUCTS: tuple[Construct, ...] = (
    NETHER_CONSTRUCTS
    + END_CONSTRUCTS
    + WITHER_CONSTRUCTS
    + BUCKET_CONSTRUCTS
    + SNIFFER_CONSTRUCTS
    + (CASTING,)
)


def by_product() -> dict[str, list[Construct]]:
    """产出（能力或物品）→ 产出它的构造。"""
    index: dict[str, list[Construct]] = {}
    for construct in CONSTRUCTS:
        index.setdefault(construct.product, []).append(construct)
    return index


def placeholder_prefix(name: str) -> str | None:
    """`capability:lava_access@*` → `capability:lava_access`；不是占位符返回 `None`。"""
    if not name.endswith("@*"):
        return None
    return name[:-2]
