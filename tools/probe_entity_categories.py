"""核实实体分类分布，判断怪物/水生是否真的没刷出来。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

doc = json.loads((Path(sys.argv[1]) / "entity-census.json").read_text(encoding="utf-8"))
result = doc["result"]

print(f"扫描区块 {result['chunks']}  实体总数 {result['entities']}")
print(f"chunksWithEntities {result['chunksWithEntities']}")
print()
print("按分类：")
for category, cell in result["byCategory"].items():
    print(f"  {category:<10} count={cell['count']:<6} types={cell['types']:<4} perChunk={cell['perChunk']}")

print()
print("按类型（前 30）：")
for name, cell in list(result["byType"].items())[:30]:
    print(f"  {name:<34} {cell['category']:<9} count={cell['count']:<6} perChunk={cell['perChunk']}")

monsters = [n for n, c in result["byType"].items() if c["category"] == "monster"]
water = [n for n, c in result["byType"].items() if c["category"] == "water"]
print()
print(f"monster 类型数 {len(monsters)}: {monsters}")
print(f"water 类型数 {len(water)}: {water}")
