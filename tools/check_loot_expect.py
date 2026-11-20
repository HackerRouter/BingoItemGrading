"""快速验证期望引擎在若干真实表上的输出。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bingo_grading.loot.expect import expect  # noqa: E402
from bingo_grading.loot.tables import load  # noqa: E402

tables = load([ROOT / "ref" / "RecipeAnalysis" / "inputs" / "26.3" / "data"])
print(f"表数 {len(tables)}，损坏 {len(tables.broken)}")

for table_id in ("minecraft:blocks/oak_leaves", "minecraft:chests/simple_dungeon"):
    for tool_probability, label in ((0.0, "徒手"), (1.0, "带工具")):
        result = expect(table_id, tables, tool_probability=tool_probability)
        items = ", ".join(
            f"{name.split(':')[1]}={value:.4f}"
            for name, value in sorted(result.per_item.items())
            if value
        )
        print(f"\n{table_id}  [{label}]  total={result.total_items:.3f}")
        print(f"  {items}")
        if result.assumptions:
            print(f"  假设: {result.assumptions}")
        if result.unsupported:
            print(f"  不支持: {result.unsupported}")

print("\n=== 抽查几个箱子表")
for table_id in (
    "minecraft:chests/abandoned_mineshaft",
    "minecraft:chests/buried_treasure",
    "minecraft:chests/end_city_treasure",
):
    result = expect(table_id, tables)
    iron = result.per_item.get("minecraft:iron_ingot", 0)
    diamond = result.per_item.get("minecraft:diamond", 0)
    print(
        f"  {table_id:<40} total={result.total_items:>7.3f} "
        f"iron={iron:>7.4f} diamond={diamond:>7.4f} unsupported={len(result.unsupported)}"
    )
