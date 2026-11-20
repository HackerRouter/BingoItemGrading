"""核对上游战利品表事实相对原始数据包丢失了哪些结构。

逐表对比：原始 JSON 的 weight / 嵌套组数量 / count 形态，
与事实里的记录做差集。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

raw_root = Path(sys.argv[1])  # .../inputs/26.3/data/minecraft/loot_table
facts_path = Path(sys.argv[2])  # .../output/26.3/facts/loot_table.jsonl

facts = {}
for line in facts_path.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    row = json.loads(line)
    payload = row.get("payload") or {}
    if payload.get("table"):
        facts[payload["table"]] = payload

raw_weight = 0
raw_entries = 0
raw_nested = 0
raw_count_kinds = Counter()
raw_pools = 0

for path in raw_root.rglob("*.json"):
    rel = path.relative_to(raw_root).with_suffix("")
    table = f"minecraft:{rel.as_posix()}"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        continue
    for pool in doc.get("pools") or []:
        raw_pools += 1

        def walk(entries):
            global raw_entries, raw_weight, raw_nested
            for entry in entries or []:
                raw_entries += 1
                if "weight" in entry:
                    raw_weight += 1
                if entry.get("type") in ("minecraft:alternatives", "minecraft:group", "minecraft:sequence"):
                    raw_nested += 1
                walk(entry.get("children"))
                for fn in entry.get("functions") or []:
                    count = fn.get("count")
                    if isinstance(count, dict):
                        raw_count_kinds[count.get("type")] += 1
                    elif count is not None:
                        raw_count_kinds["<literal>"] += 1

        walk(pool.get("entries"))

print("=== 原始数据包")
print(f"表数 {len(facts)}（事实侧）/ 池数 {raw_pools}")
print(f"条目 {raw_entries}，带 weight {raw_weight}，嵌套组 {raw_nested}")
print(f"count 形态 {dict(raw_count_kinds)}")

fact_entries = sum(
    len(pool.get("entries") or []) for payload in facts.values() for pool in payload.get("pools") or []
)
fact_weight = sum(
    1
    for payload in facts.values()
    for pool in payload.get("pools") or []
    for entry in pool.get("entries") or []
    if "weight" in entry
)
fact_children = Counter(
    entry.get("children")
    for payload in facts.values()
    for pool in payload.get("pools") or []
    for entry in pool.get("entries") or []
)
print("\n=== 上游事实")
print(f"条目 {fact_entries}，带 weight {fact_weight}")
print(f"children 取值分布 {dict(fact_children)}")

print("\n=== 差集")
print(f"丢失 weight：{raw_weight - fact_weight} 条")
print(f"丢失嵌套组层级：{raw_nested} 个（事实里 children 全为 0 表示已摊平）")
