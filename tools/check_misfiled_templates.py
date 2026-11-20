"""核对被错名的模板是否带战利品表：证明缺口在命名，不在数据。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RA = ROOT / "data" / "upstream" / "26.3" / "recipe-analysis"
NAMES = ("barracks", "chamber_1", "sauna_1", "tall_ruin_1", "ice_box_1")


def main() -> None:
    rows = [json.loads(line) for line in (RA / "facts" / "template.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    for name in NAMES:
        hit = [row["payload"] for row in rows if row["payload"].get("template") == name]
        if not hit:
            print(f"{name:<14} 未导出")
            continue
        payload = hit[0]
        tables = payload.get("loot_tables") or []
        print(
            f"{name:<14} blocks={payload['block_count']:<6} "
            f"loot_tables={len(tables)} {tables[:2]} "
            f"be={payload.get('block_entity_ids')}"
        )


if __name__ == "__main__":
    main()
