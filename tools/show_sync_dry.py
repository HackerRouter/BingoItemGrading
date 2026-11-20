"""展示 `bg data sync` 的 dry-run 结果。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bingo_grading import upstream  # noqa: E402

report = upstream.sync("26.3", dry_run=True)
lines: list[str] = []
lines.append(f"条目 {len(report.entries)}，跳过 {len(report.skipped)}")
total = 0
for entry in report.entries:
    total += entry.bytes
    lines.append(
        f"  {entry.kind:<34}{entry.layer:<8}{entry.files:>6} 文件 {entry.bytes / 1048576:>8.2f} MB"
    )
    lines.append(f"      {entry.source} -> {entry.target}")
for note in report.skipped:
    lines.append(f"  跳过: {note}")
lines.append(f"合计 {total / 1048576:.2f} MB")

root = Path(__file__).resolve().parents[1]
out = root / "build" / "sync-dry.txt"
out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print(f"written {out}")
