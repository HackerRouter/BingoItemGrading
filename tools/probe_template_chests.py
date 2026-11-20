"""检查上游 template 事实是否已记录结构模板里的箱子与战利品表。"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

path = Path(sys.argv[1]) / "template.jsonl"
rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
print(f"template 事实 {len(rows)} 条")
print("顶层键", sorted(rows[0]))
print("payload 键", sorted((rows[0].get("payload") or {})))

loot_holders = Counter()
sample = None
for row in rows:
    payload = row.get("payload") or {}
    holder = payload.get("holder") or payload.get("id") or ""
    for block in payload.get("blocks") or []:
        name = block.get("id") or block.get("name") or ""
        if name.endswith("chest") or name.endswith("barrel") or "chest" in name:
            loot_holders[holder] += 1
            if sample is None:
                sample = (holder, block)

print(f"\n含箱子的模板数 {len(loot_holders)}，箱子总数 {sum(loot_holders.values())}")
for holder, count in loot_holders.most_common(8):
    print(f"  {holder:<60} {count}")

if sample:
    print("\n样例箱子条目：", json.dumps(sample, ensure_ascii=False)[:400])

# 看 blocks 的字段
for row in rows:
    payload = row.get("payload") or {}
    blocks = payload.get("blocks") or []
    if blocks:
        print("\n首个模板的 blocks[0]：", json.dumps(blocks[0], ensure_ascii=False)[:300])
        print("模板 id：", payload.get("holder") or payload.get("id"))
        print("其余 payload 字段：", {k: v for k, v in payload.items() if k != "blocks"})
        break

# 是否有模板引用战利品表
print("\n含 loot_table 字样的模板：")
count = 0
for row in rows:
    payload = row.get("payload") or {}
    text = json.dumps(payload, ensure_ascii=False)
    if "loot_table" in text or "LootTable" in text:
        count += 1
        if count <= 2:
            print(f"  {payload.get('holder') or payload.get('id')}（长度 {len(text)}）")
print(f"  共 {count} 条")
