"""核实恶地金矿高密度的成因：查原始数据包里的 placed_feature 与群系引用。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])  # .../inputs/26.3/data/minecraft/worldgen

biome = json.loads((root / "biome" / "badlands.json").read_text(encoding="utf-8"))
features = biome.get("features") or []
print("=== badlands features（按 step）")
for step, entries in enumerate(features):
    ores = [entry for entry in entries if "gold" in str(entry) or "ore" in str(entry)]
    if ores:
        print(f"  step {step}: {ores}")

print()
for name in ("ore_gold", "ore_gold_extra", "ore_gold_lower", "ore_gold_buried"):
    for folder, key in (("placed_feature", "placement"), ("feature", "")):
        path = root / folder / f"{name}.json"
        if not path.exists():
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        if folder == "placed_feature":
            placement = doc.get("placement") or []
            count = next((p for p in placement if p.get("type") == "minecraft:count"), None)
            height = next((p for p in placement if p.get("type") == "minecraft:height_range"), None)
            print(f"{name} (placed): count={count}  height={height}")
        else:
            config = (doc.get("config") or {})
            print(f"{name} (feature): size={config.get('size')}  targets={[t.get('target') for t in config.get('targets') or []]}")
