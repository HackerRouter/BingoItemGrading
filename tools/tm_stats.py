"""把 TimingMeasurements 的原始记录折算成可回填 `gamedata.py` 的统计量。

数据有两个来源，tick 基准相同（都是该玩家所在世界的 gametime），但格式不同：

- 模组 `tmeter.csv`：`tick,event,player,dim,x,y,z,item`，一行一个事件。
- 数据包 `latest.log`：`TM <event> <player> d=<间隔> t=<gametime>`，
  `d` 是该玩家距**上一次任意** TM 事件的 tick 数，所以**不能**当同类事件间隔用
  ——本脚本一律用 `t` 排序后自己求差。

回填用的是**均值**（模型对时间求和，见 timing-constants-plan.md §1），
中位数与 IQR 只作参考：右偏分布上中位数必然偏低。

用法：
    python tools/tm_stats.py
    python tools/tm_stats.py --csv <tmeter.csv> --log <latest.log>
    python tools/tm_stats.py --only TRADE_SECONDS,FISH_SECONDS
    python tools/tm_stats.py --min-samples 30

退出码：0 = 至少一条常量拿到了样本；1 = 一条都没有（通常意味着链路没通）。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / "ref" / "TimingMeasurements" / "fabric-timer" / "run"
DEFAULT_CSV = DEFAULT_RUN / "tmeter.csv"
DEFAULT_LOG = DEFAULT_RUN / "logs" / "latest.log"

TICKS_PER_SECOND = 20.0
BOOTSTRAP_ROUNDS = 10_000
BOOTSTRAP_SEED = 20_261_121
CI_LOW_PERCENT = 2.5
CI_HIGH_PERCENT = 97.5

# 数据包 tellraw 落日志时前缀是 `[hh:mm:ss] [Server thread/INFO] (Minecraft) System chat: `，
# 这里只认行内片段，前缀不参与匹配。
PACK_LINE = re.compile(r"TM (?P<event>\S+) (?P<player>\S+) d=(?P<delta>-?\d+) t=(?P<tick>-?\d+)")


@dataclass(frozen=True)
class Event:
    tick: int
    name: str
    player: str
    source: str
    item: str = ""
    # 模组 CSV 带坐标，日志不带。`kind="speed"` 靠它算位移。
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass(frozen=True)
class Spec:
    """一条常量的采样口径。

    kind="interval"：同一玩家（或整体）相邻两次同类事件的时间差。
    kind="pair"：同一玩家 start 之后的第一条 end 的时间差。
    kind="speed"：同一对 start/end 的位移除以时间，样本单位是 blocks/s。
    """

    constant: str
    kind: str
    start: str
    end: str = ""
    item_prefix: str = ""
    scope: str = "player"
    note: str = ""
    # interval 用：与这些事件的 tick 相差不超过窗口的样本点作废（而不是删掉再连差），
    # 因为删掉中间点会让两侧的间隔变成跨点差，直接翻倍。
    drop_near: tuple[str, int] | None = None


# `item_prefix` 只在模组 CSV 上生效（日志里没有物品列）。
SPECS: dict[str, Spec] = {
    # —— 点击类 / 输入速率：连续两次同类事件 ——
    "TRADE_SECONDS": Spec(
        "TRADE_SECONDS", "interval", "trade",
        note="每次交易摊销；20 次以上的总时长 / 次数",
    ),
    "FISH_SECONDS": Spec(
        "FISH_SECONDS", "interval", "fish",
        note="抛竿到下次抛竿；应接近 17.5s 机制值 + 收线周转",
    ),
    "SUSPICIOUS_SECONDS": Spec(
        "SUSPICIOUS_SECONDS", "interval", "tool_wear", item_prefix="minecraft:brush",
        note="刷子相邻耐久事件，机制应 ≈ 96 tick",
    ),
    "SHEAR_SECONDS": Spec(
        "SHEAR_SECONDS", "interval", "shear",
        note="右键到下次右键；含界面/输入周转",
    ),
    # 模组没有容器关闭事件，GUI 类改用吞吐量：连做 N 次，只在首尾各打一个 mark，
    # 配 --count N 摊销。这也正是 plan §6 对 CRAFT / TRADE 的要求（「每分钟几次」）。
    "CHEST_SECONDS": Spec(
        "CHEST_SECONDS", "pair", "mark:chest_begin", "mark:chest_end",
        note="吞吐量：连开 N 个箱子，--count N",
    ),
    "CRAFT_SECONDS_PER_STEP": Spec(
        "CRAFT_SECONDS_PER_STEP", "pair", "mark:craft_begin", "mark:craft_end",
        note="吞吐量：连摆 N 次配方，--count N；2×2 与 3×3 分开跑",
    ),
    "ANVIL_USE_SECONDS": Spec(
        "ANVIL_USE_SECONDS", "pair", "mark:anvil_begin", "mark:anvil_end",
        note="吞吐量：连修 N 次，--count N",
    ),
    "BARTER_SECONDS": Spec(
        "BARTER_SECONDS", "pair", "use_entity:minecraft:piglin",
        "pickup:minecraft:item",
        note="扔金锭到捡回交换物；机制下界 6s",
    ),
    "POT_SECONDS": Spec(
        "POT_SECONDS", "interval", "break_block:minecraft.decorated_pot",
        note="走近被打包进窗口，需与距离项择一",
    ),
    "CROP_HARVEST_SECONDS": Spec(
        "CROP_HARVEST_SECONDS", "interval", "break_block:minecraft.wheat",
        note="单株收获；连续收获的相邻差",
    ),
    "RESIN_HIT_SECONDS": Spec(
        "RESIN_HIT_SECONDS", "interval", "attack_entity:minecraft:creaking",
        note="机制 5s 冷却；只在夜晚、heart 已连接时有意义",
    ),
    "KILL_SECONDS": Spec(
        "KILL_SECONDS", "pair", "task_begin:kill", "task_end:kill",
        note=(
            "抽到任务 -> 目标僵尸死亡；含走位与暴击节奏"
            "（不能用 attack_entity->death 配对：致死那一击和死亡同 tick，恒为 0）"
        ),
    ),
    "SPAWNER_WAIT_SECONDS": Spec(
        "SPAWNER_WAIT_SECONDS", "interval", "entity_load:minecraft:zombie",
        scope="global",
        note="需清场后计时；均匀分布 10–39.95s，报分布不报中位数",
        # 模组会给 kill 任务召唤僵尸；那些加载与刷怪笼无关，且它们贴着 task_begin
        # 写入。新模组已经把召唤物记成 entity_load:tm_target，这里是历史数据的丢弃规则。
        drop_near=("task_begin:kill", 1),
    ),
    # —— D 类真人实跑：只认 /tm mark 的首尾点，每跑一次得一个样本 ——
    "HAY_FIND_SECONDS": Spec(
        "HAY_FIND_SECONDS", "pair", "mark:hay_begin", "mark:hay_end",
        note="村中心→破坏干草块；已含走位，n≥30",
    ),
    "STRUCTURE_FIND_SECONDS": Spec(
        "STRUCTURE_FIND_SECONDS", "pair", "mark:struct_begin", "mark:struct_end",
        note="结构入口→第一个容器；与模型的距离项择一，防重复计算",
    ),
    "WITHER_FIGHT_SECONDS": Spec(
        "WITHER_FIGHT_SECONDS", "pair", "mark:wither_begin", "mark:wither_end",
        note="召唤→血条清零；n≥10，记装备",
    ),
    "WITHER_TUNNEL": Spec(
        "WITHER_TUNNEL", "pair", "task_begin:wither_tunnel", "task_end:wither_tunnel",
        note="1 格宽 x 90 格长窄道，凋灵进不来只能正面打：全铁 + 弓 + 面包 + 工作台",
    ),
    "WITHER_CAGE": Spec(
        "WITHER_CAGE", "pair", "task_begin:wither_cage", "task_end:wither_cage",
        note="3x3x3 基岩笼，凋灵被卡住不能近身（安全打法下界）",
    ),
    "DRAGON_FIGHT_SECONDS": Spec(
        "DRAGON_FIGHT_SECONDS", "pair", "task_begin:dragon", "task_end:dragon",
        note="进末地 -> 龙蛋入手，测整体不分段；下面三条是分段",
    ),
    # 龙战分四段。mod 自动打三个点：
    #   mark:dragon_spawned  龙出现在场上
    #   mark:dragon_crystals 回血水晶清空（此时龙已存在）
    #   mark:dragon_killed   龙死
    # task_end 是龙蛋进背包。
    #
    # `DRAGON_PREP` 是「放水晶 + 等复活」，统计上当作搭路成本的替身：
    # 我们无法每场重现从出生平台搭桥（玩家搭的会留下，挖掉的也恢复不了），
    # 所以直接把玩家放在主岛上，用复活等待换掉那段。两者量级相当但不相关。
    "DRAGON_PREP": Spec(
        "DRAGON_PREP", "pair", "task_begin:dragon", "mark:dragon_spawned",
        note="触发复活 -> 龙出现。只有复活读秒，不含搭桥（搭桥已由这段替代）",
    ),
    "DRAGON_CLEAR_CRYSTALS": Spec(
        "DRAGON_CLEAR_CRYSTALS", "pair", "mark:dragon_spawned", "mark:dragon_crystals",
        note="龙出现 -> 柱子上 10 个回血水晶全清",
    ),
    "DRAGON_KILL": Spec(
        "DRAGON_KILL", "pair", "mark:dragon_crystals", "mark:dragon_killed",
        note="水晶清空 -> 龙死；这是真正的「打龙」时长，给 DRAGON_FIGHT_SECONDS",
    ),
    "DRAGON_EGG": Spec(
        "DRAGON_EGG", "pair", "mark:dragon_killed", "task_end:dragon",
        note="龙死 -> 龙蛋入手；破蛋那一段",
    ),
    "EXPLORE": Spec(
        "EXPLORE", "pair", "task_begin:explore", "task_end:explore",
        note="从随机地表落点跑到水平 300 格；取整段时长。产出的是地表真实速度，"
             "用来核对 RUN_BLOCKS_PER_TU=5.612 是否偏乐观（不是 factor）",
    ),
    "EXPLORE_UNDERGROUND": Spec(
        "EXPLORE_UNDERGROUND", "pair", "task_begin:explore_underground", "task_end:explore_underground",
        note="真实洞穴/矿道内水平路径 100 格，只计 underground 环境。"
             "factor = 5.612 × (秒数/100)，直接就是 UNDERGROUND_MOVE_FACTOR",
    ),
    "EXPLORE_WATER": Spec(
        "EXPLORE_WATER", "pair", "task_begin:explore_water", "task_end:explore_water",
        note="真实海里潜游水平路径 100 格，只计 underwater 环境。"
             "factor = 5.612 × (秒数/100)，直接就是 UNDERWATER_MOVE_FACTOR",
    ),
    "WATER_MINE": Spec(
        "WATER_MINE", "pair", "task_begin:water_mine", "task_end:water_mine",
        note="固定水洞（灌水洞穴 + 气室 + 四壁铁矿）里挖满 5 块铁矿；"
             "量的是「水下作业一次要多久」，不是流动系数——找矿、换气、游泳全在里面",
    ),
    "STRUCTURE_FIND": Spec(
        "STRUCTURE_FIND", "pair", "task_begin:village_chest", "task_end:village_chest",
        note="落在随机村庄内部 -> 打开第一个容器；该时长就是 STRUCTURE_FIND_SECONDS",
    ),
    # —— 移动倍率：同一条跑道上首尾各打一个 mark，位移由坐标算 ——
    # 实际速度与 `SPRINT_BLOCKS_PER_SECOND`（5.612 m/s）的比值就是模型的倍率。
    "MOVE_SURFACE": Spec(
        "MOVE_SURFACE", "speed", "mark:surf_begin", "mark:surf_end",
        note="地表疾跑道 64 格；基准值应为 5.61 m/s",
    ),
    "MOVE_TUNNEL": Spec(
        "MOVE_TUNNEL", "speed", "mark:tunnel_begin", "mark:tunnel_end",
        note="1x2 矿道疾跑 64 格；地表/这个 = UNDERGROUND_MOVE_FACTOR",
    ),
    "MOVE_WATER": Spec(
        "MOVE_WATER", "speed", "mark:water_begin", "mark:water_end",
        note="水下游泳 64 格；地表/这个 = UNDERWATER_MOVE_FACTOR",
    ),
}

# 工位随机任务的 id，与模组 TimingMeter.TASKS 一一对应。
# 每轮由 /tmark next 写 task_begin:<id>，完成时写 task_end:<id>。
# kill 也在这张表里，但它量的是「击杀一只怪」，直接记为 KILL_SECONDS，
# 所以不在这里重复登记一遍。
TASK_IDS = (
    "chest",
    "craft2",
    "craft3",
    "repair",
    "shear",
    "milk",
    "honey",
    "brush",
    "bucket",
    "scoop",
    "pot",
    "crop",
    "bonemeal",
)

for _tid in TASK_IDS:
    SPECS[f"task:{_tid}"] = Spec(
        f"task:{_tid}",
        "pair",
        f"task_begin:{_tid}",
        f"task_end:{_tid}",
        note="工位随机任务：抽到 -> 完成（含 3 秒倒数之后）",
    )


# 只用于体检：这些事件名说明链路是通的，但不直接对应常量。
SANITY = ("use_block", "use_entity", "attack_entity", "break_block", "trade", "fish", "mark")


def parse_csv(path: Path) -> tuple[list[Event], int]:
    """读模组 CSV。返回 (事件, 跳过行数)。

    第一列不是整数就跳过（表头、半行、其他进程写入的脏数据）。
    """
    events: list[Event] = []
    skipped = 0
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.reader(fh):
            if len(row) < 3:
                skipped += 1
                continue
            try:
                tick = int(row[0])
            except ValueError:
                skipped += 1
                continue
            item = row[7] if len(row) > 7 else ""
            events.append(
                Event(
                    tick,
                    row[1],
                    row[2],
                    "mod",
                    item,
                    _coord(row, 4),
                    _coord(row, 5),
                    _coord(row, 6),
                )
            )
    return events, skipped


def _coord(row: list[str], index: int) -> float:
    """坐标列可能缺或带脏值，算不出来就当 0（speed 口径自己会跳过零位移）。"""
    if len(row) <= index:
        return 0.0
    try:
        return float(row[index])
    except ValueError:
        return 0.0


def parse_log(path: Path) -> tuple[list[Event], int]:
    """读数据包写在 latest.log 里的 TM 行。"""
    events: list[Event] = []
    skipped = 0
    if not path.exists():
        return events, 0
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "TM " not in line:
                continue
            match = PACK_LINE.search(line)
            if not match:
                skipped += 1
                continue
            events.append(
                Event(
                    int(match.group("tick")),
                    match.group("event"),
                    match.group("player"),
                    "pack",
                )
            )
    return events, skipped


def extract(spec: Spec, events: list[Event]) -> list[float]:
    """按口径抽样本，返回 tick 差列表（已按玩家分组，不跨玩家配对）。"""
    if spec.scope == "player":
        groups: dict[str, list[Event]] = {}
        for ev in events:
            if spec.item_prefix and not ev.item.startswith(spec.item_prefix):
                continue
            groups.setdefault(ev.player, []).append(ev)
        buckets = list(groups.values())
    else:
        buckets = [events]

    deltas: list[float] = []
    for bucket in buckets:
        ordered = sorted(
            (ev for ev in bucket if spec.item_prefix == "" or ev.item.startswith(spec.item_prefix)),
            key=lambda ev: ev.tick,
        )
        if spec.kind == "interval":
            hits = [ev.tick for ev in ordered if ev.name == spec.start]
            keep = [True] * len(hits)
            if spec.drop_near:
                near_name, window = spec.drop_near
                anchors = [ev.tick for ev in ordered if ev.name == near_name]
                keep = [not any(abs(t - a) <= window for a in anchors) for t in hits]
            for i in range(len(hits) - 1):
                if keep[i] and keep[i + 1]:
                    deltas.append(float(hits[i + 1] - hits[i]))
        elif spec.kind == "pair":
            pending: int | None = None
            for ev in ordered:
                if ev.name == spec.start:
                    pending = ev.tick
                elif ev.name == spec.end and pending is not None:
                    deltas.append(float(ev.tick - pending))
                    pending = None
        else:
            raise ValueError(f"未知 kind: {spec.kind}")
    return [d for d in deltas if d >= 0]


def extract_speed(spec: Spec, events: list[Event]) -> list[float]:
    """按坐标算平均移动速度（blocks/s）。

    只取水平位移：跑道的上下起伏不属于移动倍率，且 y 的跳动（台阶、游泳上浮）
    会让三维距离偏大。位移为 0 的配对直接丢弃（忘了跑、或两次打点站原地）。
    """
    groups: dict[str, list[Event]] = {}
    for ev in events:
        groups.setdefault(ev.player, []).append(ev)
    speeds: list[float] = []
    for bucket in groups.values():
        ordered = sorted(bucket, key=lambda ev: ev.tick)
        pending: Event | None = None
        for ev in ordered:
            if ev.name == spec.start:
                pending = ev
            elif ev.name == spec.end and pending is not None:
                ticks = ev.tick - pending.tick
                distance = math.hypot(ev.x - pending.x, ev.z - pending.z)
                if ticks > 0 and distance > 0:
                    speeds.append(distance / (ticks / TICKS_PER_SECOND))
                pending = None
    return speeds


def summarize_speed(values: list[float]) -> dict[str, float | int]:
    """速度样本的统计量。单位是 blocks/s，列名不能沿用 time 口径。"""
    ordered = sorted(values)
    mean = statistics.fmean(ordered)
    std = statistics.stdev(ordered) if len(ordered) >= 2 else 0.0
    median = statistics.median(ordered)
    return {
        "n": len(ordered),
        "mean_bps": round(mean, 3),
        "std_bps": round(std, 3),
        "cv": round(std / mean, 3) if mean else 0.0,
        "median_bps": round(median, 3),
        "min_bps": round(ordered[0], 3),
        "max_bps": round(ordered[-1], 3),
    }


def summarize(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    mean = statistics.fmean(ordered)
    std = statistics.stdev(ordered) if len(ordered) >= 2 else 0.0
    if len(ordered) >= 2:
        q1, _, q3 = statistics.quantiles(ordered, n=4, method="inclusive")
    else:
        q1 = q3 = ordered[0]
    # 95 分位：样本少时退化为最大值，够用；后面的方差链路要 p95 而不是只用均值。
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    rng = random.Random(BOOTSTRAP_SEED)
    means = []
    for _ in range(BOOTSTRAP_ROUNDS):
        means.append(statistics.fmean(rng.choices(ordered, k=len(ordered))))
    means.sort()
    lo = means[int(len(means) * CI_LOW_PERCENT / 100)]
    hi = means[int(len(means) * CI_HIGH_PERCENT / 100)]
    return {
        "n": len(ordered),
        "mean_ticks": round(mean, 2),
        "mean_seconds": round(mean / TICKS_PER_SECOND, 3),
        "std_seconds": round(std / TICKS_PER_SECOND, 3),
        "cv": round(std / mean, 3) if mean else 0.0,
        "p95_seconds": round(p95 / TICKS_PER_SECOND, 3),
        "median_ticks": round(statistics.median(ordered), 2),
        "iqr_ticks": [round(q1, 2), round(q3, 2)],
        "min_ticks": round(ordered[0], 2),
        "max_ticks": round(ordered[-1], 2),
        "ci95_mean_seconds": [round(lo / TICKS_PER_SECOND, 3), round(hi / TICKS_PER_SECOND, 3)],
    }


def health(events: list[Event]) -> dict[str, int]:
    """链路体检：每类事件出现几次。全 0 说明 trigger 或回调没通。"""
    counts: dict[str, int] = {}
    for ev in events:
        head = ev.name.split(":", 1)[0]
        counts[head] = counts.get(head, 0) + 1
    return counts


def render(report: dict[str, dict], only: set[str]) -> str:
    lines = [
        f"{'constant':<20}{'n':>4}{'mean_s':>9}{'std_s':>8}{'cv':>7}{'p95_s':>8}"
        f"{'median_s':>10}{'ci95(mean_s)':>18}",
        "-" * 84,
    ]
    for name in sorted(report):
        if only and name not in only:
            continue
        row = report[name]
        if row.get("kind") == "speed":
            continue
        if "error" in row:
            lines.append(f"{name:<20}{'-':>4}  {row['error']}")
            continue
        stats = row["stats"]
        ci = f"{stats['ci95_mean_seconds'][0]:.2f}-{stats['ci95_mean_seconds'][1]:.2f}"
        lines.append(
            f"{name:<20}{stats['n']:>4}{stats['mean_seconds']:>9.3f}"
            f"{stats['std_seconds']:>8.3f}{stats['cv']:>7.2f}{stats['p95_seconds']:>8.3f}"
            f"{stats['median_ticks'] / TICKS_PER_SECOND:>10.3f}{ci:>18}"
        )
    speed_rows = [
        name
        for name in sorted(report)
        if report[name].get("kind") == "speed" and (not only or name in only)
    ]
    if speed_rows:
        lines.append("")
        lines.append(f"{'move track':<20}{'n':>4}{'mean_bps':>10}{'std':>8}{'cv':>7}{'median':>9}{'min':>8}{'max':>8}")
        lines.append("-" * 74)
        for name in speed_rows:
            row = report[name]
            if "error" in row:
                lines.append(f"{name:<20}{'-':>4}  {row['error']}")
                continue
            stats = row["stats"]
            lines.append(
                f"{name:<20}{stats['n']:>4}{stats['mean_bps']:>10.3f}"
                f"{stats['std_bps']:>8.3f}{stats['cv']:>7.2f}"
                f"{stats['median_bps']:>9.3f}{stats['min_bps']:>8.3f}{stats['max_bps']:>8.3f}"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="模组输出的 tmeter.csv")
    parser.add_argument("--log", type=Path, action="append", help="数据包 TM 行所在的日志，可重复给")
    parser.add_argument("--out", type=Path, help="默认写到 CSV 同目录的 tm_stats.json")
    parser.add_argument("--only", help="只算这些常量，逗号分隔")
    parser.add_argument("--min-samples", type=int, default=1, help="低于该样本数只报 warning")
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="每个窗口内做了几次（吞吐量法摊销，如连做 20 次合成给 20）",
    )
    args = parser.parse_args(argv)
    if args.count < 1:
        parser.error("--count 必须 >= 1")

    events: list[Event] = []
    skipped = 0
    if args.csv.exists():
        parsed, bad = parse_csv(args.csv)
        events.extend(parsed)
        skipped += bad
    else:
        print(f"[warn] csv 不存在: {args.csv}", file=sys.stderr)

    for log in args.log or [DEFAULT_LOG]:
        parsed, bad = parse_log(log)
        events.extend(parsed)
        skipped += bad

    only = {part.strip() for part in args.only.split(",")} if args.only else set()
    report: dict[str, dict] = {}
    for name, spec in SPECS.items():
        if only and name not in only:
            continue
        if spec.kind == "speed":
            speeds = extract_speed(spec, events)
            if not speeds:
                report[name] = {"error": "no samples", "note": spec.note, "kind": "speed"}
                continue
            report[name] = {"note": spec.note, "kind": "speed", "stats": summarize_speed(speeds)}
            continue
        values = [v / args.count for v in extract(spec, events)]
        if not values:
            report[name] = {"error": "no samples", "note": spec.note}
            continue
        stats = summarize(values)
        entry: dict = {"note": spec.note, "kind": spec.kind, "stats": stats}
        if stats["n"] < args.min_samples:
            entry["warning"] = f"n={stats['n']} < min-samples={args.min_samples}"
        report[name] = entry

    out = args.out or (args.csv.parent / "tm_stats.json")
    payload = {
        "events_total": len(events),
        "skipped_lines": skipped,
        "per_window_count": args.count,
        "health": health(events),
        "constants": report,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"events={len(events)} skipped={skipped} -> {out}")
    counts = payload["health"]
    missing = [key for key in SANITY if counts.get(key, 0) == 0]
    if missing:
        print(f"[warn] 以下事件一次都没出现，链路可能没通: {', '.join(missing)}")
    print(render(report, only))

    return 0 if any("stats" in row for row in report.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
