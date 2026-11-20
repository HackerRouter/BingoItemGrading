"""看上游 recipe 的 kind 分布与熔炼条目。"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parents[1]
facts = root / "ref" / "RecipeAnalysis" / "output" / "26.3" / "facts"


def rows(name: str):
    for line in (facts / name).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            yield json.loads(line)


kinds = Counter()
samples: dict[str, dict] = {}
gold_hits = []
for row in rows("recipe.jsonl"):
    kind = row.get("kind")
    kinds[kind] += 1
    samples.setdefault(kind, row)
    text = json.dumps(row, ensure_ascii=False)
    if "gold_ingot" in text or "raw_gold" in text:
        gold_hits.append(row)

print("== recipe.jsonl kind 分布 ==")
for kind, count in kinds.most_common():
    print(f"  {kind:<24}{count}")

print("\n== 每种 kind 的第一条 ==")
for kind, row in samples.items():
    print(f"\n--- {kind} ---")
    print(json.dumps(row, ensure_ascii=False)[:500])

print(f"\n== recipe 里含 gold_ingot / raw_gold 的条目：{len(gold_hits)} ==")
for row in gold_hits[:8]:
    print(json.dumps(row, ensure_ascii=False)[:500])
