"""核对上游 facts 是否保留了容器战利品表的 weight / quality。"""

from __future__ import annotations

import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / "ref" / "RecipeAnalysis" / "output" / "26.3" / "facts" / "loot_table.jsonl"

lines: list[str] = []


def say(text: str = "") -> None:
    lines.append(text)


target = None
stats = {"tables": 0, "with_weight": 0, "with_quality": 0, "with_rolls": 0}
for raw in path.read_text(encoding="utf-8").splitlines():
    raw = raw.strip()
    if not raw:
        continue
    row = json.loads(raw)
    payload = row.get("payload") or {}
    table = payload.get("table")
    if not table:
        continue
    stats["tables"] += 1
    text = json.dumps(payload, ensure_ascii=False)
    if '"weight"' in text:
        stats["with_weight"] += 1
    if '"quality"' in text:
        stats["with_quality"] += 1
    if '"rolls"' in text:
        stats["with_rolls"] += 1
    if table == "minecraft:chests/simple_dungeon" and target is None:
        target = payload

say(f"总表数 {stats['tables']}，含 weight {stats['with_weight']}，"
    f"含 quality {stats['with_quality']}，含 rolls {stats['with_rolls']}")
say("")
if target is not None:
    say("== minecraft:chests/simple_dungeon 的 payload（节选）==")
    say(json.dumps(target, ensure_ascii=False, indent=1)[:2000])
else:
    say("facts 里没有 simple_dungeon 表")

out = root / "build" / "facts-weight-check.txt"
out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print(f"written {out}")
