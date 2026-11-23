"""共享常量与小工具：节点表、代码注入来源、维度门、递归深度。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from bingo_grading import paths
from bingo_grading import gamedata
from bingo_grading.case.sources import seconds
from bingo_grading.sources.knowledge import load_structure_maps


def cost_cv(
    ctx,
    subject: str,
    item: str,
    expected: float,
    *,
    condition: str = "tools=tools=present",
) -> float:
    """战利品来源的**成本**相对标准差，喂给 `Action.yield_cv`。

    `loot_expectation.per_trigger_cv` 是「一次触发产出的波动」（`s/μ`），而
    `Segment.cv` 要的是「凑够 1 件的成本波动」。凑 `n` 件所需的触发次数本身
    是随机的，renewal 近似下 `Var(n 件) = n·c²·s²/μ³`；换算到单价 `c/μ` 上
    正好是 `(s/μ)·√μ`，所以这里要乘 `√expected`。

    这个公式与需求量无关（`n` 只在消费者那边乘），所以批量来源（μ > 1）
    也能用：μ=22 时 `cv` 大，但 `unit = c/μ` 很小，两者相抵消，n=1 时
    方差只占成本的 1% 量级——与「跑一趟就够了」的直觉一致。
    真正的陷阱在消费端：不能用整次取整后的 `calls` 去乘（见 `grade.best_whole_cost`）。
    """
    if expected <= 0:
        return 0.0
    return ctx.loot_cv(subject, item, condition=condition) * math.sqrt(expected)



# 配方链递归上限。铁锭 → 铁块 → 铁粒 → ... 这类环靠 `stack` 截断，
# 深度上限只是防住没被 `stack` 抓到的长链。
MAX_DEPTH = 6


# 熔炼类序列化器：这些不是「组装」，是「一进一出加时间」，
# 成本里要含熔炉时间与燃料。
SMELT_SERIALIZERS = ("minecraft:smelting", "minecraft:blasting")


# 这些表不是结构：由玩家行为触发（出生奖励、钓鱼、猪灵以物易物、英雄赠礼）。
# 与「缺映射」分开记账，否则报告里看不出哪些是真缺口。
NON_STRUCTURE_TABLES = (
    "chests/spawn_bonus_chest",
    "gameplay/fishing/",
    "gameplay/piglin_bartering",
    "gameplay/hero_of_the_village/",
    "gameplay/turtle_grow",
    "gameplay/sniffer_digging",
    "gameplay/chicken_lay",
    "brush/armadillo",
)



@dataclass(frozen=True)
class NodeTable:
    """一类「节点型来源」：玩家先满足一个状态，然后反复触发。

    `once` 里的名字可以是 `capability:`（能力）、物品名（工具，递归定价）。
    没有来源的 `capability:` 不是错误：它表示「这个状态尚未建模」，
    路线会因不可达被引擎标出，而不是静默消失。
    """

    marker: str
    action_prefix: str
    seconds: float
    once: tuple[str, ...] = ()
    per_use: tuple[tuple[str, float], ...] = ()
    note: str = ""



# 顺序敏感：先匹配前面的。
NODE_TABLES = (
    NodeTable(
        "gameplay/fishing/",
        "fish",
        gamedata.FISH_SECONDS,
        once=("minecraft:fishing_rod",),
        note="先有钓竿：每次抛竿等咬钩",
    ),
    NodeTable(
        "gameplay/piglin_bartering",
        "barter",
        gamedata.BARTER_SECONDS,
        once=("capability:nether_access",),
        per_use=(("minecraft:gold_ingot", 1.0),),
        note="到得了下界、手里有金锭：一次投咦换一份掉落",
    ),
    NodeTable(
        "gameplay/hero_of_the_village/",
        "gift",
        gamedata.GIFT_SECONDS,
        once=("capability:hero_of_the_village",),
        note="英雄赠礼：需要先打赢一场袭击（该状态尚无建模与数据）",
    ),
    NodeTable(
        "gameplay/cat_morning_gift",
        "cat_gift",
        # 一天只有**睡觉后**的一次抽奖机会：多人服不会一起睡，单人晚上能早睡
        # 但还要打怪，实际就是「一个游戏日一次」，不能按「摸一下猫」计价。
        gamedata.CAT_GIFT_SECONDS,
        once=("capability:minecraft:villages", "minecraft:cod"),
        note="驯服的猫每天早晨送礼物：先到村庄找猫、用生鳕鱼驯服",
    ),
    NodeTable(
        "gameplay/turtle_grow",
        "grow",
        gamedata.TURTLE_EGG_HATCH_SECONDS + gamedata.TURTLE_GROW_SECONDS,
        once=("minecraft:turtle_egg",),
        note="海龟蛋孵出小海龟、再等它长成成年海龟才蜕下 1 个鳞甲",
    ),
    NodeTable(
        "gameplay/sniffer_digging",
        "dig",
        gamedata.SNIFFER_DIG_COOLDOWN_SECONDS,
        once=("capability:adult_sniffer",),
        note="成年嗅探兽刨地：刨一次后冷却 8 分钟",
    ),
    NodeTable(
        "gameplay/chicken_lay",
        "lay",
        gamedata.CHICKEN_EGG_SECONDS,
        once=("capability:minecraft:villages",),
        note="成年鸡每 5–10 分钟下一个蛋：先到村庄或平原找到鸡",
    ),
    NodeTable(
        "brush/armadillo",
        "brush",
        gamedata.SUSPICIOUS_SECONDS,
        note="用刷子梳理犰狳，它会蜕下 1 个鳞甲（不含找犰狳的路程）",
    ),
    NodeTable(
        "chests/spawn_bonus_chest",
        "bonus",
        0.0,
        once=("capability:world_spawn",),
        note="出生点奖励箱：只在开局出现一次",
    ),
)


def _node_table(subject: str) -> NodeTable | None:
    _, _, rest = subject.partition(":")
    for node in NODE_TABLES:
        if node.marker in rest:
            return node
    return None


# 「代码里直接塞进结构」的物品。上游给的是代码引用，不是战利品表：
#   `code:structure_gadgets:.../EndCityPieces.java:item:minecraft:elytra#841`
# 这种来源没法按表名映射，只能显式写「哪个结构 + 什么载体 + 每个载体几个」。
#
# 末地船的鞘翅挂在物品展示框里，而展示框不会出现在战利品表中——它是结构
# 生成时直接放的实体。数据里就体现为 `end_cities` 的
# `entities_per_start["minecraft:item_frame"] = 0.44`，即约 44% 的末地城带船。
GADGET_SOURCES: dict[str, tuple[str, str, float, str]] = {
    # marker（出现在 subject 里的代码名）→ (结构集合, 载体实体, 每个载体给几个, 物品)
    "EndCityPieces": (
        "minecraft:end_cities",
        "minecraft:item_frame",
        1.0,
        "minecraft:elytra",
    ),
}



def _gadget_for(subject: str) -> tuple[str, str, float, str] | None:
    for marker, entry in GADGET_SOURCES.items():
        if marker in subject:
            return entry
    return None



# 去这些维度要先开门。前置名与案例层的 `capability:` 同一套。
# 开门本身也是构造（`constructs.py` 的 `end:portal`），所以这里只指路：
# 末地门 = 要塞框架 + 12 个末影之眼 = 末影珍珠 + 烈焰粉 → 必须先过下界。
DIMENSION_ACCESS = {
    "minecraft:the_nether": "capability:nether_access",
    "minecraft:the_end": "capability:the_end_access",
}


# 没有等级划分的商人（目前只有流浪商人）。他的报价在 `trade_offer` 里的
# subject 是 `minecraft:wandering_trader`，前置是一个**故意不造来源**的能力：
# 随机遭遇频率还没有数据，不能拿村庄的行程成本冒充。
WANDERING_TRADER = "wandering_trader"

WANDERING_TRADER_CAP = "capability:wandering_trader"


# `binding:template-item:<容器>:<物品>`：模板里放了这个容器、容器里有这件东西。
# 上游没给战利品表名，属于模板解析（R4）的范围，不是「表名丢了」。
BINDING_PREFIX = "binding:template-item:"


# 成窝生成、不能按散点密度外推的方块。
#
# 紫水晶洞是个球形空腔：洞壁密布芽与簇。按「挖穿岩层平均挖 1/ρ 块碰到一块」
# 算，实测会得到 6360 TU（密度 0.0539/区块 ÷ 4096 格³）。真实打法是找到一个洞、
# 把里面一堆成熟簇一次采走，所以走 `mine_geode()`。
GEODE_SOURCES = frozenset({"minecraft:amethyst_cluster"})


# 只在 creaking heart 旁生成的方块。它们没有散点密度，走 `resin_farm()`：
# 夜里打嘎枝 → heart 在相连原木上长 2–3 块 → 挖走（5 秒冷却，可无限重复）。
RESIN_SOURCES = frozenset({"minecraft:resin_clump"})



def default_index(pack: str) -> Path:
    return paths.BUILD_ROOT / pack / "source_index.jsonl"



def _is_non_structure(subject: str) -> bool:
    """这张表是不是玩家行为触发的（而不是结构里找到的）。"""
    _, _, rest = subject.partition(":")
    return any(marker in rest for marker in NON_STRUCTURE_TABLES)



def _short(name: str) -> str:
    """短标识：战利品表取可区分的末段，其余保留原样。

    - `minecraft:chests/village/village_toolsmith` → `village_toolsmith`
    - `minecraft:pots/trial_chambers/corridor` → `pots_trial_chambers_corridor`
      （**不能**只取末段：`chests/trial_chambers/corridor` 也叫 `corridor`，
      两张表会撞成同一个动作 ID，后一张被去重丢掉）
    - `minecraft:cleric/1` → `cleric/1`（职业/等级是整体，不能只留 `1`）
    - `minecraft:villages` → `villages`
    """
    if name.startswith("minecraft:"):
        name = name[len("minecraft:") :]
    head, sep, tail = name.partition("/")
    if not sep:
        return name
    if head in ("chests", "barrels", "dispensers", "equipment", "spawners"):
        return tail.split("/")[-1]
    if head in ("pots", "archaeology"):
        return f"{head}_{tail.replace('/', '_')}"
    if head == "gameplay":
        return tail.split("/")[-1]
    return name



@lru_cache(maxsize=1)
def _structure_maps():
    """结构集合映射。与 `CaseContext` 用的是同一份文件，读一次缓存。"""
    from bingo_grading import paths

    return load_structure_maps(paths.KNOWLEDGE_ROOT / "structure_sets.toml")
