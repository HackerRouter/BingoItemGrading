"""检查带权重的表是否保留了 weight（看 simple_dungeon / fishing）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1]) / "loot_table.jsonl"
rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

want = {
    "minecraft:chests/simple_dungeon",
    "minecraft:gameplay/fishing/fish",
    "minecraft:chests/village/village_toolsmith",
}
for row in rows:
    payload = row.get("payload") or {}
    if payload.get("table") not in want:
        continue
    print("=" * 70)
    print(payload["table"], "pools=", len(payload.get("pools") or []))
    for index, pool in enumerate(payload.get("pools") or []):
        entries = pool.get("entries") or []
        print(f"  pool {index}: rolls={pool.get('rolls')!r} entries={len(entries)} conditions={pool.get('conditions')}")
        if entries:
            print("    首个条目：", json.dumps(entries[0], ensure_ascii=False)[:400])
        kinds = {}
        for entry in entries:
            kinds[entry.get("kind")] = kinds.get(entry.get("kind"), 0) + 1
        print("    条目 kind 分布：", kinds)
        keys = set()
        for entry in entries:
            keys |= set(entry)
        print("    条目键并集：", sorted(keys))
