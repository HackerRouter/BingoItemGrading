"""看村民交易里与红石相关的条目。"""

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


print("== 产出 redstone 的交易 ==")
count = 0
by_profession: Counter[str] = Counter()
for row in rows("trade.jsonl"):
    payload = row.get("payload") or {}
    gives = payload.get("gives") or {}
    if gives.get("id") != "minecraft:redstone":
        continue
    count += 1
    by_profession[payload.get("profession")] += 1
    print(json.dumps(payload, ensure_ascii=False)[:400])

print(f"\n共 {count} 条，职业分布 {dict(by_profession)}")

print("\n== cleric 全部交易 ==")
for row in rows("trade.jsonl"):
    payload = row.get("payload") or {}
    if payload.get("profession") != "cleric":
        continue
    wants = payload.get("wants") or {}
    gives = payload.get("gives") or {}
    print(
        f"  level={payload.get('level')}  "
        f"{wants.get('count')}×{wants.get('id')} → "
        f"{gives.get('count')}×{gives.get('id')}  "
        f"max_uses={(payload.get('meta') or {}).get('max_uses')}"
    )
