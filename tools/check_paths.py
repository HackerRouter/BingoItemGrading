"""验证 data/ 本地化后的解析结果与校验。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bingo_grading import paths, upstream  # noqa: E402

root = Path(__file__).resolve().parents[1]
lines: list[str] = []


def say(text: str = "") -> None:
    lines.append(text)


say("== 解析层（应全部 local）==")
summary = paths.summary("26.3")
say(f"  fully_local = {summary['fully_local']}")
for name, item in summary["sources"].items():
    say(f"  {name:<20}{item['layer']:<10}exists={item['exists']}  {item['path']}")

say("")
say("== manifest 校验 ==")
result = upstream.verify("26.3")
say(f"  ok={result.ok}  已校验 {result.checked} 条")
for problem in result.problems:
    say(f"  问题: {problem}")

say("")
say("== data/ 体积 ==")
for sub in ("vanilla", "upstream"):
    path = paths.DATA_ROOT / sub
    if not path.exists():
        continue
    files = [p for p in path.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    say(f"  data/{sub:<10}{len(files):>6} 文件 {total / 1048576:>8.2f} MB")

out = root / "build" / "paths-check.txt"
out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print(f"written {out}")
