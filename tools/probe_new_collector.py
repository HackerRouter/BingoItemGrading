"""查看新版采集产物：target 头部、biome-ore、biome-patch 结构。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

run = Path(sys.argv[1])
lines: list[str] = []


def dump(name: str, limit: int = 2600) -> None:
    path = run / name
    if not path.exists():
        lines.append(f"\n=== {name}  不存在")
        return
    doc = json.loads(path.read_text(encoding="utf-8"))
    text = json.dumps(doc, ensure_ascii=False, indent=1)
    lines.append(f"\n=== {name}  ({path.stat().st_size} bytes)")
    lines.append(text[:limit])
    if len(text) > limit:
        lines.append(f"... 截断，总长 {len(text)}")


dump("summary.json", 3000)
dump("biome-ore.json", 3500)
dump("biome-patch.json", 3000)

out = Path(sys.argv[2])
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"{out}  {out.stat().st_size} bytes")
