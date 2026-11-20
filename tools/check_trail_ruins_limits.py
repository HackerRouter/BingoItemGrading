"""按处理器 `limit` 而不是「行数」核算 trail_ruins 的可刷扫点。

处理器型容器（`trail_ruins_*_archaeology`）一行代表「最多替换 N 个方块」，
不是「一个方块」。这里比较三种口径：
- 行数（当前实现）
- `limit` 之和（处理器语义）
- 采集侧实测
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RA = ROOT / "data" / "upstream" / "26.3" / "recipe-analysis"
RUN = sorted((ROOT / "data" / "upstream" / "26.3" / "worldgen-stats").iterdir())[-1]
STRUCTURE = "minecraft:trail_ruins"


def main() -> None:
    per_template: dict[str, tuple[int, int]] = {}
    for line in (RA / "export" / "template_containers.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        name = row.get("template")
        if not isinstance(name, str):
            continue
        rows, limits = per_template.get(name, (0, 0))
        rows += 1
        limit = row.get("limit")
        limits += int(limit) if isinstance(limit, (int, float)) else 1
        per_template[name] = (rows, limits)

    payload = json.loads((RUN / "structure-interior.overworld.json").read_text(encoding="utf-8"))
    entry = next(
        item
        for item in payload["result"]["minecraft:overworld"]["structures"]
        if item["structure"] == STRUCTURE
    )
    placed = [(e["template"].split(":", 1)[-1], float(e.get("perStart") or 0)) for e in entry["templates"]]

    by_rows = 0.0
    by_limits = 0.0
    for name, per_start in placed:
        rows, limits = per_template.get(name, (0, 0))
        by_rows += rows * per_start
        by_limits += limits * per_start

    measured = sum((entry.get("lootTables") or {}).values()) / entry["starts"]
    print(f"片段/实例 {entry['piecesPerStart']:.1f}  实例 {entry['starts']}")
    print(f"按行数计：{by_rows:.1f}/实例")
    print(f"按 limit 计：{by_limits:.1f}/实例")
    print(f"采集侧实测：{measured:.1f}/实例")
    print(f"limit/行数 = {by_limits / by_rows:.2f}   实测/limit = {measured / by_limits:.2f}")


if __name__ == "__main__":
    main()
