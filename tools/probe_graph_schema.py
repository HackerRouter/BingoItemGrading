"""打印 graph.json 的顶层结构、节点/边类型分布与样本。

用法：python tools/probe_graph_schema.py [pack]
输出写到 build/graph-schema.txt（UTF-8），终端只打印路径。
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = sys.argv[1] if len(sys.argv) > 1 else "26.3"
GRAPH = ROOT / "data" / "upstream" / PACK / "recipe-analysis" / "graph.json"
OUT = ROOT / "build" / "graph-schema.txt"


def main() -> None:
    doc = json.loads(GRAPH.read_text(encoding="utf-8"))
    lines: list[str] = []
    lines.append(f"# {GRAPH}")
    lines.append(f"top-level keys: {sorted(doc)}")
    for key, value in doc.items():
        if isinstance(value, list):
            lines.append(f"  {key}: list len={len(value)}")
        elif isinstance(value, dict):
            lines.append(f"  {key}: dict keys={sorted(value)[:12]}")
        else:
            lines.append(f"  {key}: {type(value).__name__} = {value!r}")
    lines.append("")

    for key in ("nodes", "edges", "rules", "seeds"):
        rows = doc.get(key) or []
        if not rows:
            continue
        lines.append(f"## {key}: {len(rows)}")
        if not isinstance(rows[0], dict):
            lines.append(f"first: {json.dumps(rows[:5], ensure_ascii=False)}")
            lines.append("")
            continue
        fields = collections.Counter()
        for row in rows:
            if isinstance(row, dict):
                fields.update(row.keys())
        lines.append(f"fields: {dict(fields.most_common())}")
        kind_key = "kind" if any("kind" in r for r in rows if isinstance(r, dict)) else None
        if kind_key:
            dist = collections.Counter(str(r.get("kind")) for r in rows if isinstance(r, dict))
            lines.append(f"kind 分布: {dict(dist.most_common())}")
        for row in rows[:3]:
            lines.append(json.dumps(row, ensure_ascii=False))
        lines.append("")
        # 同一 kind 的样本（如果有更多种）
        if kind_key:
            seen: dict[str, dict] = {}
            for row in rows:
                if isinstance(row, dict):
                    seen.setdefault(str(row.get("kind")), row)
            for kind, row in seen.items():
                lines.append(f"-- {key} kind={kind}:")
                lines.append(json.dumps(row, ensure_ascii=False))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
