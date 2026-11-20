"""作物自然生长：从战利品表取成熟阶段数，用随机刻机制模拟期望时长。

模型（Java 版最佳条件）：

- 随机刻：每个子区块每 tick 抽 `random_tick_speed` 次，每次在 16³ 格里均匀选一格；
- 被抽中后按 `nextInt((int)(25/speed)+1)==0` 推进一个阶段；
- `speed`（`getGrowthSpeed`）在「湿润耕地 + 3×3 全是耕地 + 无相邻同种作物」时
  = 1 + 3（中心格 moisture>0）+ 8×(3/4) = 10 → `(int)(25/10)+1 = 3` → p = 1/3。
"""

import json
import random

SUBSECTION_VOLUME = 16 * 16 * 16
TICKS_PER_SECOND = 20
RANDOM_TICK_SPEED = 3
GROWTH_SPEED_BEST = 10.0

LOOT_FACTS = "data/upstream/26.3/recipe-analysis/facts/loot_table.jsonl"
CROPS = ("wheat", "carrot", "potato", "beetroot", "torchflower", "pitcher")


def _is_match_block(node):
    kind = str(node.get("type") or node.get("condition") or "")
    return kind.endswith("match_block")


def collect_mature_age(payload, table, found):
    if isinstance(payload, dict):
        if _is_match_block(payload):
            state = payload.get("state") or {}
            raw = state.get("age")
            if isinstance(raw, str) and raw.isdigit():
                found[table] = max(found.get(table, 0), int(raw))
        for value in payload.values():
            collect_mature_age(value, table, found)
    elif isinstance(payload, list):
        for value in payload:
            collect_mature_age(value, table, found)


found = {}
with open(LOOT_FACTS, encoding="utf-8") as fh:
    for line in fh:
        row = json.loads(line)
        table = (row.get("payload") or {}).get("table") or ""
        collect_mature_age(row.get("payload"), table, found)

print("== 战利品表里出现过的成熟 age ==")
for table, age in sorted(found.items()):
    if any(key in table for key in CROPS):
        print(f"  {table:38} age={age}")

divisor = int(25.0 / GROWTH_SPEED_BEST) + 1
print(f"\n最佳条件：speed={GROWTH_SPEED_BEST} → 每阶段判定分母 {divisor}（p=1/{divisor}）")


def simulate(max_age, trials=800, seed=20261119):
    rng = random.Random(seed)
    total = 0
    for _ in range(trials):
        age = 0
        ticks = 0
        while age < max_age:
            ticks += 1
            for _ in range(RANDOM_TICK_SPEED):
                if rng.randrange(SUBSECTION_VOLUME) != 0:
                    continue
                if rng.randrange(divisor) != 0:
                    continue
                age += 1
                if age >= max_age:
                    break
        total += ticks
    return total / trials / TICKS_PER_SECOND


print("\n== 模拟（单株，最佳条件）==")
print(f"{'阶段数':>6} {'秒':>10} {'分钟':>8} {'解析值':>10}")
analytic_unit = divisor * SUBSECTION_VOLUME / RANDOM_TICK_SPEED / TICKS_PER_SECOND
for max_age in (1, 3, 4, 7):
    seconds = simulate(max_age)
    print(
        f"{max_age:>6} {seconds:>10.1f} {seconds / 60:>8.2f} "
        f"{max_age * analytic_unit:>10.1f}"
    )
print(f"\n每阶段解析值 = {analytic_unit:.2f} 秒（模拟值应对得上）")
