"""导出 biome-patch 单体条目与 biome-ore 的群系覆盖情况。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

run = Path(sys.argv[1])
out = Path(sys.argv[2])
lines: list[str] = []

patch = json.loads((run / "biome-patch.json").read_text(encoding="utf-8"))
result = patch["result"]["minecraft:overworld"]
lines.append("=== biome-patch result 顶层键")
lines.append(json.dumps({k: (type(v).__name__) for k, v in result.items()}, ensure_ascii=False, indent=1))
lines.append("\n=== biome-patch 首个群系条目")
biomes = result.get("biomes") or []
lines.append(json.dumps(biomes[0], ensure_ascii=False, indent=1) if biomes else "(空)")
lines.append(f"\n群系条目数 {len(biomes)}")
lines.append("\n=== 全部群系的关键字段")
for biome in biomes:
    patches = biome.get("patches") or {}
    lines.append(
        f"{biome['id']:<42} columns={biome.get('columns'):<9} "
        f"reliable={biome.get('reliable')} patches={patches.get('count')} "
        f"meanArea={patches.get('meanAreaBlocks')} open={biome.get('openSurfaceShare')}"
    )

ore = json.loads((run / "biome-ore.json").read_text(encoding="utf-8"))
ores = ore["result"]["minecraft:overworld"]
lines.append("\n=== biome-ore result 顶层键")
lines.append(json.dumps({k: (type(v).__name__) for k, v in ores.items()}, ensure_ascii=False, indent=1))
lines.append(f"\n群系数 {len(ores.get('biomes') or [])}，reliableBiomes={ores.get('reliableBiomes')} minChunks={ores.get('minChunks')}")
lines.append("\n=== biome-ore 每个群系的矿石数与非零矿种")
for biome in ores.get("biomes") or []:
    nonzero = {
        name: round(cell["avgPerChunk"], 4)
        for name, cell in (biome.get("ores") or {}).items()
        if cell.get("count")
    }
    lines.append(
        f"{biome['id']:<42} chunks={biome.get('chunks'):<6} reliable={biome.get('reliable')} "
        f"矿种={len(nonzero)} {list(nonzero.items())[:4]}"
    )

out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"{out}  {out.stat().st_size} bytes")
