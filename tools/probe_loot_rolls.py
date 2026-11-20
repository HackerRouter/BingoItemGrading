"""检查 loot_table 事实是否含 rolls 与 weight。"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

path = Path(sys.argv[1]) / "loot_table.jsonl"
rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

pool_keys: Counter = Counter()
entry_keys: Counter = Counter()
roll_kinds: Counter = Counter()
has_weight = 0
entries_total = 0
count_kinds: Counter = Counter()
funcs: Counter = Counter()

for row in rows:
    payload = row.get("payload") or {}
    for pool in payload.get("pools") or []:
        for key in pool:
            pool_keys[key] += 1
        for entry in pool.get("entries") or []:
            entries_total += 1
            for key in entry:
                entry_keys[key] += 1
            if "weight" in entry:
                has_weight += 1
            for fn in entry.get("functions") or []:
                funcs[fn.get("function")] += 1
                count = fn.get("count")
                if isinstance(count, dict):
                    count_kinds[count.get("type")] += 1

print("pool 键:", dict(pool_keys))
print("entry 键:", dict(entry_keys))
print(f"条目总数 {entries_total}，带 weight 的 {has_weight}")
print("functions:", dict(funcs))
print("set_count 的 count.type:", dict(count_kinds))

# rolls 的实际取值形态
rolls_samples = []
for row in rows:
    payload = row.get("payload") or {}
    for pool in payload.get("pools") or []:
        if "rolls" in pool:
            rolls_samples.append((payload.get("table"), pool["rolls"]))
print("\nrolls 样例：")
for table, rolls in rolls_samples[:6]:
    print(f"  {table:<52} {rolls}")

# 一个多池表
print("\n未找到 rolls 字段的池数：", pool_keys.get("rolls", 0) == 0)
