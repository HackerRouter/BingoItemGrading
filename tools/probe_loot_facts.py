"""查看上游 loot_table 事实是否含 pools / rolls / weights。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1]) / "loot_table.jsonl"
rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
print(f"行数 {len(rows)}")
print(f"顶层键 {sorted(rows[0])}")

# 挑 village_toolsmith
target = None
for row in rows:
    payload = row.get("payload") or {}
    if payload.get("table") == "minecraft:chests/village/village_toolsmith":
        target = row
        break

if target is None:
    print("未找到 village_toolsmith")
    for row in rows[:3]:
        print(json.dumps(row, ensure_ascii=False)[:600])
    sys.exit(0)

print("\n=== village_toolsmith 完整结构（截断展示）")
text = json.dumps(target, ensure_ascii=False, indent=1)
print(text[:4000])
print(f"... 总长 {len(text)}")
