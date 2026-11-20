"""清点 `match_block` 条件：哪些只判方块身份，哪些还判方块状态。

背景：掉率求值遇到不认识的条件按「不成立」算（概率 0），于是整池归零。
需要方块状态分布的那些条件，就是上游新增分析器的理由。

输出到 build/match-block.txt。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bingo_grading import paths  # noqa: E402

OUT = ROOT / "build" / "match-block.txt"
BASE_KEYS = {"type", "blocks", "block", "condition"}


def walk(node, sink: list[dict]) -> None:
    if isinstance(node, dict):
        raw = node.get("type") or node.get("condition")
        if isinstance(raw, str) and raw.endswith("match_block"):
            sink.append(node)
        for value in node.values():
            walk(value, sink)
    elif isinstance(node, list):
        for item in node:
            walk(item, sink)


def main() -> None:
    root = paths.loot_tables("26.3").path
    stateful: dict[str, list[str]] = {}
    identity: list[str] = []
    for path in sorted(root.rglob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        sink: list[dict] = []
        walk(doc, sink)
        for node in sink:
            extra = {key: value for key, value in node.items() if key not in BASE_KEYS}
            table = path.relative_to(root).with_suffix("").as_posix()
            if extra:
                stateful.setdefault(table, []).append(json.dumps(extra, ensure_ascii=False))
            else:
                identity.append(table)

    lines = [
        f"含 match_block 的表：{len(set(stateful) | set(identity))}",
        f"纯身份判定（无状态键）：{len(identity)} 张表",
        f"带状态判定：{len(stateful)} 张表",
        "",
        "== 带状态判定的表（前 40）==",
    ]
    for table, extras in sorted(stateful.items())[:40]:
        lines.append(f"  {table:<40} {extras[:3]}")
    lines.append("")
    lines.append("== 纯身份判定的表（前 20）==")
    for table in sorted(set(identity))[:20]:
        lines.append(f"  {table}")
    lines.append("")
    kinds = Counter()
    for extras in stateful.values():
        for raw in extras:
            for key in json.loads(raw):
                kinds[key] += 1
    lines.append(f"状态键分布：{dict(kinds.most_common())}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
