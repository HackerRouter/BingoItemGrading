"""把全仓 Markdown 里指向 docs 的链接改到新位置。

按「文件当前所在目录」计算相对路径，所以 docs 内部互引、adr 的 `../`、
根 README 的 `docs/...`、plan 的 `../docs/...` 都会被改对。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 旧文件名 → 新绝对路径
TARGETS = {
    "upstream-requirements.md": "docs/contracts/upstream-requirements.md",
    "recipe-analysis-requirements.md": "docs/contracts/recipe-analysis-requirements.md",
    "upstream-changes.md": "docs/contracts/upstream-changes.md",
    "task-split.md": "docs/contracts/task-split.md",
    # 旧 collector-requirements 被拆成两份，默认指主契约
    "collector-requirements.md": "docs/contracts/collector-contract.md",
    "sources.md": "docs/data/sources.md",
    "stats.md": "docs/data/stats.md",
    "data-source-audit.md": "docs/data/data-source-audit.md",
    "units.md": "docs/data/units.md",
    "framework-boundary.md": "docs/model/framework-boundary.md",
    "covered-register.md": "docs/model/covered-register.md",
    "gap-register.md": "docs/model/gap-register.md",
    "design-route-competition.md": "docs/model/route-competition.md",
    # 改名过的 ADR：旧名仍被引用
    "0017-upstream-presence-semantics.md": "docs/adr/0017-loot-expectation-owned-downstream.md",
}

# 移动后 docs 子目录里的 adr/ 都要上跳一层
ADR_PREFIX = "adr/"

SKIP_DIRS = (".venv", "build", "ref", "data", "node_modules")

LINK = re.compile(r"\[(?P<text>[^\]]*)\]\((?P<path>[^)\s]+?\.md)(?P<anchor>#[^)]*)?\)")


def rewrite(md: Path) -> int:
    text = md.read_text(encoding="utf-8")
    here = md.parent

    def fix(match: re.Match[str]) -> str:
        raw = match.group("path")
        name = Path(raw).name
        target = TARGETS.get(name)
        if target is None and raw.startswith(ADR_PREFIX):
            candidate = ROOT / "docs" / "adr" / name
            if candidate.exists():
                target = f"docs/adr/{name}"
        if target is None:
            return match.group(0)
        absolute = ROOT / target
        rel = os.path.relpath(absolute, here).replace("\\", "/")
        return f"[{match.group('text')}]({rel}{match.group('anchor') or ''})"

    new = LINK.sub(fix, text)
    if new == text:
        return 0
    md.write_text(new, encoding="utf-8")
    return 1


def main() -> None:
    changed = 0
    for md in ROOT.rglob("*.md"):
        if any(part in SKIP_DIRS for part in md.parts):
            continue
        changed += rewrite(md)
    print(f"改动文件 {changed} 个")


if __name__ == "__main__":
    main()
