"""核对绿宝石的村民交易来源，以及牧师红石交易的等级。"""

from __future__ import annotations

import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
facts = root / "ref" / "RecipeAnalysis" / "output" / "26.3" / "facts"


def rows(name: str):
    for line in (facts / name).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            yield json.loads(line)


print("== 用农产品/粘土换绿宝石的交易 ==")
CHEAP = {"minecraft:wheat", "minecraft:clay_ball", "minecraft:potato", "minecraft:carrot",
         "minecraft:beetroot", "minecraft:stone", "minecraft:andesite", "minecraft:diorite",
         "minecraft:granite", "minecraft:pumpkin", "minecraft:melon", "minecraft:string"}
for row in rows("trade.jsonl"):
    payload = row.get("payload") or {}
    gives = payload.get("gives") or {}
    wants = payload.get("wants") or {}
    if gives.get("id") != "minecraft:emerald":
        continue
    if wants.get("id") not in CHEAP:
        continue
    meta = payload.get("meta") or {}
    print(
        f"  {payload.get('profession'):<14} lv{payload.get('level')}  "
        f"{wants.get('count')}×{wants.get('id'):<28}"
        f"→ {gives.get('count')} emerald  max_uses={meta.get('max_uses')}"
    )

print("\n== 牧师红石交易的完整 payload ==")
for row in rows("trade.jsonl"):
    payload = row.get("payload") or {}
    gives = payload.get("gives") or {}
    if gives.get("id") == "minecraft:redstone":
        print(json.dumps(row, ensure_ascii=False, indent=2))
