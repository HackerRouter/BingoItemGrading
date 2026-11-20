"""探测统计产物结构，供人工审阅。

不猜字段：把每个 JSON 的顶层键、两层以内的形状、以及关键值的样例打出来。
输出写 UTF-8 文件，避免终端代码页问题。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MAX_SAMPLES = 3


def shape(value, depth: int = 0) -> str:
    if isinstance(value, dict):
        if depth >= 2:
            return "object"
        keys = list(value)[:12]
        parts = [f"{key}: {shape(value[key], depth + 1)}" for key in keys]
        more = "" if len(value) <= 12 else f", …（共 {len(value)} 键）"
        return "{" + ", ".join(parts) + more + "}"
    if isinstance(value, list):
        if not value:
            return "array[0]"
        return f"array[{len(value)}] of {shape(value[0], depth + 1)}"
    if isinstance(value, str):
        text = value if len(value) <= 60 else value[:57] + "…"
        return f'"{text}"'
    return type(value).__name__ if not isinstance(value, bool) else f"bool({value})"


def main() -> int:
    base = Path(sys.argv[1])
    out = Path(sys.argv[2])
    lines: list[str] = []

    for path in sorted(base.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        lines.append(f"\n{'=' * 70}\n{path.name}  ({path.stat().st_size} bytes)\n{'=' * 70}")
        lines.append("顶层：" + shape(doc, 0))

        result = doc.get("result") if isinstance(doc, dict) else None
        if isinstance(result, dict):
            lines.append("\nresult 形状：")
            for key, value in result.items():
                lines.append(f"  {key}: {shape(value, 1)}")

            for key, value in result.items():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    lines.append(f"\nresult[{key!r}] 样例（前 {min(MAX_SAMPLES, len(value))} 条）：")
                    for item in value[:MAX_SAMPLES]:
                        lines.append("  " + json.dumps(item, ensure_ascii=False))
                elif isinstance(value, dict):
                    nested = [k for k, v in value.items() if isinstance(v, (list, dict))]
                    if nested:
                        lines.append(f"\nresult[{key!r}] 子键：")
                        for sub in nested:
                            lines.append(f"  {sub}: {shape(value[sub], 1)}")
                            inner = value[sub]
                            if isinstance(inner, list) and inner and isinstance(inner[0], dict):
                                for item in inner[:MAX_SAMPLES]:
                                    lines.append("    " + json.dumps(item, ensure_ascii=False))
                            elif isinstance(inner, dict):
                                lines.append("    " + json.dumps(inner, ensure_ascii=False)[:600])
        elif result is not None:
            lines.append("\nresult：" + json.dumps(result, ensure_ascii=False)[:800])

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{out}  {out.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
