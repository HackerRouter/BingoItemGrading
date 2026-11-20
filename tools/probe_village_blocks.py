"""从 village 模板统计干草块、粘土等方块的数量。"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parents[1]
facts = root / "ref" / "RecipeAnalysis" / "output" / "26.3" / "facts"

WATCH = ("minecraft:hay_block", "minecraft:clay", "minecraft:wheat", "minecraft:carrots", "minecraft:potatoes")

per_template: dict[str, Counter] = {}
for line in (facts / "template.jsonl").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line:
        continue
    row = json.loads(line)
    payload = row.get("payload") or {}
    template = payload.get("template")
    if not isinstance(template, str) or "village" not in template:
        continue
    counter: Counter[str] = Counter()
    for block in payload.get("blocks") or []:
        if not isinstance(block, str):
            continue
        base = block.split("{", 1)[0]
        if base in WATCH:
            counter[base] += 1
    if counter:
        per_template[template] = counter

print(f"含关注的村庄模板数: {len(per_template)}")
totals: Counter[str] = Counter()
for template, counter in per_template.items():
    totals.update(counter)
    print(f"  {template:<52}{dict(counter)}")

print("\n== 汇总 ==")
for block, count in totals.most_common():
    print(f"  {block:<26}{count}")

print("\n== 每个模板的数量分布（干草块）==")
hay = [c.get("minecraft:hay_block", 0) for c in per_template.values()]
nonzero = [x for x in hay if x]
print(f"  有干草块的模板数: {len(nonzero)} / {len(per_template)}")
if nonzero:
    print(f"  有干草块的模板中 min/median/max: {min(nonzero)}/{sorted(nonzero)[len(nonzero)//2]}/{max(nonzero)}")

print("\n== 上游 worldgen 中的 clay feature ==")
for line in (facts / "worldgen.jsonl").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line:
        continue
    if "clay" not in line:
        continue
    row = json.loads(line)
    prov = (row.get("prov") or {}).get("file", "")
    if "ore" in prov or "clay" in prov:
        print(f"  {prov}")
