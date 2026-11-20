"""估算数据缺口影响多少物品与槽位。

把「某类统计缺失」换算成「多少个物品的多少条来源失去代价输入」。
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

index_path = ROOT / "build" / "26.3" / "source_index.jsonl"
lines_list = index_path.read_text(encoding="utf-8").splitlines()
records = [json.loads(line) for line in lines_list[1:]]

# 每类来源的统计键是否可用（与 `bg data ingest` 的缺口报告同口径）
report = json.loads((ROOT / "build" / "stats-gap-report.json").read_text(encoding="utf-8"))
missing = report["source_gaps"]["missing"]
missing_set = {(stype, subject) for stype, subjects in missing.items() for subject in subjects}

by_type_items: dict[str, set[str]] = defaultdict(set)
by_type_sources: Counter = Counter()
no_stat: dict[str, set[str]] = defaultdict(set)
no_stat_sources: Counter = Counter()

for record in records:
    stype = record["source_type"]
    subject = record.get("stat_subject")
    by_type_items[stype].add(record["item"])
    by_type_sources[stype] += 1
    # 统计键缺失，或该键在缺口清单里
    if subject is None or (stype, subject) in missing_set:
        no_stat[stype].add(record["item"])
        no_stat_sources[stype] += 1

print(f"{'来源类别':<20}{'来源数':>8}{'涉及物品':>10}{'无统计来源':>12}{'受影响物品':>12}")
for stype in sorted(by_type_sources, key=lambda k: -by_type_sources[k]):
    print(
        f"{stype:<20}{by_type_sources[stype]:>8}{len(by_type_items[stype]):>10}"
        f"{no_stat_sources[stype]:>12}{len(no_stat[stype]):>12}"
    )

total_items = {record["item"] for record in records}
affected = set().union(*no_stat.values()) if no_stat else set()
print()
print(f"物品总数 {len(total_items)}，至少一条来源缺统计键的物品 {len(affected)}")

# 完全没有任何可用统计键的来源的物品
fully = []
for item in sorted(total_items):
    mine = [r for r in records if r["item"] == item]
    if all(r.get("stat_subject") is None or (r["source_type"], r["stat_subject"]) in missing_set for r in mine):
        fully.append(item)
print(f"所有来源都缺统计键的物品 {len(fully)}")
print("样例：", fully[:25])
