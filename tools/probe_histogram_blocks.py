"""从 section-block-histogram 精确读粘土、干草块、小麦的每区块数量。"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

root = Path(__file__).resolve().parents[1]
run = sorted((root / "ref" / "WorldGenStatsCollector" / "stats").iterdir())[-1]
data = json.loads((run / "section-block-histogram.json").read_text(encoding="utf-8-sig"))

WATCH = (
    "minecraft:clay",
    "minecraft:hay_block",
    "minecraft:wheat",
    "minecraft:carrots",
    "minecraft:potatoes",
    "minecraft:oak_log",
    "minecraft:short_grass",
)

for dimension, payload in (data.get("result") or {}).items():
    chunks = payload.get("chunks")
    print(f"\n===== {dimension}（{chunks} 区块）=====")
    totals: dict[str, float] = defaultdict(float)
    by_section: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for section in payload.get("sections") or []:
        y = section.get("y")
        for block in section.get("blocks") or []:
            block_id = block.get("id")
            if block_id in WATCH:
                totals[block_id] += block.get("avg") or 0.0
                by_section[block_id].append((y, block.get("avg") or 0.0))
    if not totals:
        print("  关注的方块均未出现")
        continue
    for block_id in WATCH:
        if block_id not in totals:
            continue
        print(f"  {block_id:<26}{totals[block_id]:>10.4f}/区块（全高合计）")
        for y, avg in by_section[block_id]:
            print(f"      y={y:<5}{avg:>10.4f}")
