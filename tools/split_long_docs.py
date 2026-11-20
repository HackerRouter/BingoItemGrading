"""第二轮：把仍然偏长的 docs 按节再切一刀。

按标题定位切点，不硬编码行号；同一文件有多个切点时从后往前处理。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

# (源文件, 切点标题前缀, 新文件名, 新标题, 导语)
JOBS = [
    ("model/gap-register-hard.md", "### 1.3 覆盖缺口", "model/gap-register-minor.md",
     "覆盖与精度缺口", "条目编号与 [`gap-register.md`](gap-register.md) 连续。"),
]


def main() -> None:
    # 同一文件多个切点：按出现顺序倒排处理，前面的行号不受影响。
    grouped: dict[str, list[tuple[str, str, str, str]]] = {}
    for source, marker, target, title, lead in JOBS:
        grouped.setdefault(source, []).append((marker, target, title, lead))

    for source_name, jobs in grouped.items():
        source = DOCS / source_name
        for marker, target_name, title, lead in reversed(jobs):
            lines = source.read_text(encoding="utf-8").splitlines()
            index = next(
                (i for i, line in enumerate(lines) if line.startswith(marker)), None
            )
            if index is None:
                print(f"skip   {source_name}：找不到 {marker!r}")
                continue
            body = lines[index:]
            text = f"# {title}\n\n{lead}\n\n" + "\n".join(body)
            (DOCS / target_name).write_text(text.rstrip() + "\n", encoding="utf-8")
            source.write_text("\n".join(lines[:index]).rstrip() + "\n", encoding="utf-8")
            print(f"split  {source_name} @ {marker} -> {target_name} ({len(body)} 行)")


if __name__ == "__main__":
    main()
