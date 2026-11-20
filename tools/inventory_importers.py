"""列出 worldgen 导入器各函数产出的 stat_type。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
text = (ROOT / "src" / "bingo_grading" / "stats" / "importers" / "worldgen.py").read_text(
    encoding="utf-8"
)

names = [
    "_import_lava",
    "_import_biomes",
    "_import_entities",
    "_import_structures",
    "_import_biome_patches",
    "_import_ore_stats",
    "_import_block_histogram",
]
lines = []
for name in names:
    match = re.search(rf"^def {name}\(.*?(?=^def |\Z)", text, re.S | re.M)
    if not match:
        lines.append(f"{name:<26} 未找到")
        continue
    body = match.group(0)
    kinds = sorted(set(re.findall(r'stat_type="([a-z_]+)"', body)))
    lines.append(f"{name:<26} stat_type={kinds}  行数={len(body.splitlines())}")

out = ROOT / "build" / "importers.txt"
out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print(f"written {out}")
