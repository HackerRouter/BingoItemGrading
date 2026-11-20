"""检查来源索引的概率来源分布，以及手工表里的条目是否已被数据取代。

判据：`gamedata.PROBABILITY_ROWS` 里登记的每条来源，索引里都必须变成
`yield_source=loot_expectation:...`，且数值与战利品表算出来的一致。

输出到 build/yield-sources.txt，终端只打印路径。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bingo_grading import paths  # noqa: E402
from bingo_grading.sources.knowledge import PROBABILITY_ROWS, probabilities_table  # noqa: E402

LABEL = sys.argv[1] if len(sys.argv) > 1 else "26.3"
INDEX = ROOT / "build" / LABEL / "source_index.jsonl"
OUT = ROOT / "build" / "yield-sources.txt"

# 已登记过的（物品, 来源类别, 对象）→ 期望值，用来对照
MANUAL_KEYS = [
    (item, source_type, subject, probability)
    for item, source_type, subject, probability, _ in PROBABILITY_ROWS
]


def main() -> None:
    header_line, *rows = [line for line in INDEX.read_text(encoding="utf-8").splitlines() if line.strip()]
    header = json.loads(header_line)
    records = [json.loads(line) for line in rows]
    by_source = Counter(record.get("yield_source") or "none" for record in records)
    kind = Counter(
        (record.get("yield_source") or "none").split(":")[0] for record in records
    )
    lines = [
        f"index={INDEX}",
        f"schema={header.get('index_schema')} sources={header.get('source_count')} items={header.get('item_count')}",
        f"by_yield_source_kind={dict(kind.most_common())}",
        f"manual_entries={len(by_source) and sum(v for k, v in by_source.items() if k == 'builtin_probabilities')}",
        "",
        "== 手工表条目是否已被数据取代 ==",
    ]
    index_map = {
        (record["item"], record["source_type"], record["subject"]): record for record in records
    }
    missing = 0
    for item, source_type, subject, manual in MANUAL_KEYS:
        record = index_map.get((item, source_type, subject))
        if record is None:
            lines.append(f"  未出现在索引：{item} / {source_type} / {subject}")
            missing += 1
            continue
        lines.append(
            f"  {item:<28} {source_type:<12} {subject:<26} "
            f"手工={manual:<7} 推导={record.get('yield_per_trigger')} 出处={record.get('yield_source')}"
        )
    lines.append("")
    lines.append(f"未命中的手工条目：{missing}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
