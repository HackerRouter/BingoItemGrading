"""整理 docs/：建子目录、移动文件、按节拆分三份长文档。

一次性脚本。重复运行会覆盖同名产物，不做幂等标记。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

# 旧路径（相对 docs/）→ 新路径（相对 docs/）
MOVES = {
    "upstream-requirements.md": "contracts/upstream-requirements.md",
    "recipe-analysis-requirements.md": "contracts/recipe-analysis-requirements.md",
    "upstream-changes.md": "contracts/upstream-changes.md",
    "task-split.md": "contracts/task-split.md",
    "collector-requirements.md": "contracts/collector-contract.md",
    "sources.md": "data/sources.md",
    "stats.md": "data/stats.md",
    "data-source-audit.md": "data/data-source-audit.md",
    "units.md": "data/units.md",
    "framework-boundary.md": "model/framework-boundary.md",
    "covered-register.md": "model/covered-register.md",
    "gap-register.md": "model/gap-register.md",
    "design-route-competition.md": "model/route-competition.md",
}

# 拆分：(源文件, 起始行, 结束行, 目标文件, 新标题, 导语)
# 第一段保留原文（含原 H1），其余段落新建 H1。
SPLITS = [
    (
        "collector-requirements.md",
        [
            (489, 580, "contracts/collector-conventions.md", "采集器数据形态与验收",
             "节号与 [`collector-contract.md`](collector-contract.md) 连续。"),
        ],
    ),
    (
        "gap-register.md",
        [
            (393, 471, "model/gap-register-tail.md", "缺口的影响范围与后续动作",
             "条目编号与 [`gap-register.md`](gap-register.md) 连续。"),
        ],
    ),
    (
        "design-route-competition.md",
        [
            (154, 458, "model/route-competition-scoring.md", "路线评分与顺序约束",
             "章节号与 [`route-competition.md`](route-competition.md) 连续。"),
        ],
    ),
]


def cut(src: Path, start: int, end: int) -> list[str]:
    lines = src.read_text(encoding="utf-8").splitlines()
    return lines[start - 1 : end]


def main() -> None:
    for name in ("contracts", "data", "model"):
        (DOCS / name).mkdir(exist_ok=True)

    # 1. 先切分，切点在原文件名上取，避免移动后找不到源。
    for source_name, jobs in SPLITS:
        source = DOCS / source_name
        full = source.read_text(encoding="utf-8").splitlines()
        for start, end, target_name, title, lead in jobs:
            body = full[start - 1 : end]
            text = f"# {title}\n\n{lead}\n\n" + "\n".join(body)
            (DOCS / target_name).write_text(text.rstrip() + "\n", encoding="utf-8")
            print(f"split  {source_name} [{start}..{end - 1}] -> {target_name}")
        # 源文件截断到第一段
        first_cut = min(job[0] for job in jobs)
        source.write_text(
            "\n".join(full[: first_cut - 1]).rstrip() + "\n", encoding="utf-8"
        )
        print(f"trim   {source_name} -> 1..{first_cut - 1}")

    # 2. 移动
    for old, new in MOVES.items():
        src = DOCS / old
        dst = DOCS / new
        if not src.exists():
            print(f"skip   {old}（不存在，可能已移动）")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)
        print(f"move   {old} -> {new}")


if __name__ == "__main__":
    main()
