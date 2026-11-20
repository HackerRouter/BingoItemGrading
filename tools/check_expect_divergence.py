"""清点会影响期望数值的口径分歧点。

1. 没有 `rolls` 键的池（旧实现会整池跳过，共用模块按 1 处理）
2. 同时含 `modifier` 与 `functions` 的节点（旧实现取前者，共用模块合并）
3. `type` 不带命名空间的条目

输出到 build/expect-divergence.txt，终端只打印路径。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bingo_grading import paths  # noqa: E402

OUT = ROOT / "build" / "expect-divergence.txt"


def walk(node, hits):
    if not isinstance(node, dict):
        return
    ident = node.get("type")
    if isinstance(ident, str) and ":" not in ident:
        hits["unnamespaced_type"].append(ident)
    if "modifier" in node and "functions" in node:
        hits["both_modifier_and_functions"].append(ident)
    for child in node.get("children") or []:
        walk(child, hits)


def main() -> None:
    resolved = paths.loot_tables("26.3")
    hits: dict[str, list] = {
        "pools_without_rolls": [],
        "both_modifier_and_functions": [],
        "unnamespaced_type": [],
    }
    tables = 0
    for path in sorted(resolved.path.rglob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        tables += 1
        for pool in doc.get("pools") or []:
            if isinstance(pool, dict) and "rolls" not in pool:
                hits["pools_without_rolls"].append(path.stem)
            for entry in pool.get("entries") or []:
                walk(entry, hits)

    lines = [f"tables={tables}"]
    for key, rows in hits.items():
        lines.append(f"{key}: {len(rows)}  {dict(Counter(rows).most_common(5))}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
