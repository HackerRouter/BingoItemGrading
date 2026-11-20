"""打印若干张战利品表的期望产出，用于核对具体数值。

用法：python tools/inspect_expect.py minecraft:blocks/oak_leaves minecraft:entities/witch
输出写到 build/expect-detail.txt。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bingo_grading import paths  # noqa: E402
from bingo_grading.loot.expect import expect  # noqa: E402
from bingo_grading.loot.tables import load  # noqa: E402

OUT = ROOT / "build" / "expect-detail.txt"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("用法：python tools/inspect_expect.py <table-id> [...]")
        return 1
    tables = load([paths.loot_tables("26.3").path])
    lines: list[str] = []
    for table_id in argv[1:]:
        if table_id not in tables:
            lines.append(f"{table_id}: 表不存在")
            continue
        for tool_probability in (1.0, 0.0):
            result = expect(table_id, tables, tool_probability=tool_probability)
            lines.append(
                f"{table_id} tools={tool_probability}\n"
                f"  total_items={result.total_items:.6f}\n"
                f"  per_item={json.dumps({k: round(v, 6) for k, v in sorted(result.per_item.items())}, ensure_ascii=False)}\n"
                f"  assumptions={result.assumptions}\n"
                f"  unsupported={result.unsupported}"
            )
        lines.append("")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
