"""核对上游 worldgen 事实里的「实体 × 群系」生成列表覆盖度。

如果这里已经有完整的群系刷怪列表，采集侧就完全不需要碰刷怪。
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

facts_path = Path(sys.argv[1]) / "worldgen.jsonl"
rows = [json.loads(line) for line in facts_path.read_text(encoding="utf-8").splitlines() if line.strip()]
print(f"worldgen 事实 {len(rows)} 条")

entity_biome: dict[str, set[str]] = defaultdict(set)
biome_entity: dict[str, set[str]] = defaultdict(set)
kinds: Counter = Counter()
slots: Counter = Counter()

for row in rows:
    payload = row.get("payload") or {}
    kind = payload.get("worldgen_kind")
    kinds[kind] += 1
    source = payload.get("source") or ""
    if not source.startswith("biome/"):
        continue
    biome = "minecraft:" + source.split("/", 1)[1]
    for item in payload.get("entities") or []:
        name = item if isinstance(item, str) else (item.get("id") or item.get("type"))
        if not name:
            continue
        entity_biome[name].add(biome)
        biome_entity[biome].add(name)
    slot = payload.get("slot")
    if slot:
        slots[slot] += 1

print("worldgen_kind 分布：", dict(kinds))
print("slot 分布：", dict(slots))
print(f"\n能识别出实体×群系的实体数 {len(entity_biome)}，群系数 {len(biome_entity)}")
print("\n样例（每个实体前 4 个群系）：")
for name in sorted(entity_biome)[:12]:
    print(f"  {name:<38} {sorted(entity_biome[name])[:4]}")

if not entity_biome:
    print("\n没解析出实体字段，dump 一条 biome 载荷看看：")
    for row in rows:
        payload = row.get("payload") or {}
        if str(payload.get("source", "")).startswith("biome/"):
            print(json.dumps(payload, ensure_ascii=False)[:800])
            break
