"""核对某个结构实际放置的模板里，容器数据在哪一层丢了。

对每个模板给出四列：是否导出、facts 里 loot_tables 数、容器导出表里的行数。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RA = ROOT / "data" / "upstream" / "26.3" / "recipe-analysis"
RUN = sorted((ROOT / "data" / "upstream" / "26.3" / "worldgen-stats").iterdir())[-1]


def main(argv: list[str]) -> int:
    structure = argv[1] if len(argv) > 1 else "minecraft:village_plains"
    rows = [json.loads(l) for l in (RA / "facts" / "template.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    facts = {row["payload"]["template"]: row["payload"] for row in rows if isinstance(row.get("payload"), dict)}
    containers: dict[str, int] = {}
    for line in (RA / "export" / "template_containers.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            containers[row["template"]] = containers.get(row["template"], 0) + 1

    payload = json.loads((RUN / "structure-interior.overworld.json").read_text(encoding="utf-8"))
    data = payload["result"]["minecraft:overworld"]
    entry = next(x for x in data["structures"] if x["structure"] == structure)
    placed = [(e["template"].split(":", 1)[-1], e.get("perStart") or 0) for e in entry.get("templates") or []]

    missing = 0
    facts_tables = 0
    export_rows = 0
    total = 0.0
    detail: list[str] = []
    for name, per_start in placed:
        total += per_start
        if name not in facts:
            missing += 1
            detail.append(f"  {name:<58} 未导出          perStart={per_start}")
            continue
        tables = len(facts[name].get("loot_tables") or [])
        exported = containers.get(name, 0)
        facts_tables += tables
        export_rows += exported
        if tables != exported:
            detail.append(
                f"  {name:<58} facts 表={tables:<3} 导出={exported:<3} perStart={per_start}"
            )

    print(f"{structure}: 放置模板 {len(placed)}，未导出 {missing}")
    print(f"  每实例片段合计 {total:.1f}；facts 容器数合计 {facts_tables}；导出表行合计 {export_rows}")
    for line in detail[:25]:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
