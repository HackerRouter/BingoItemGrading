"""比对 mcshared.loot 与 RecipeAnalysis 原实现的产出是否逐字节一致。

判据：把同一份战利品表 JSON 分别交给两个实现，序列化后的 payload 文本必须相同。
覆盖全量原版表 + 地形包覆盖的表。退出码 0 = 一致。

用法：python tools/check_loot_parity.py [pack]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bingo_grading import paths, upstream  # noqa: E402

# 上游 RA 的源码路径来自 config.yml，不再写死仓库内的 ref/。
sys.path.insert(0, str(paths.REF_RECIPE_ANALYSIS / "src"))

from mcshared import loot as shared  # noqa: E402
from ra.adapters.loot import LootAdapter, _table_id  # noqa: E402

PACK = sys.argv[1] if len(sys.argv) > 1 else "26.3"


def original_payload(adapter: LootAdapter, doc: dict, file_label: str):
    """RecipeAnalysis 适配器当前的构造方式，逐行照抄。"""
    table_type = doc.get("type")
    if isinstance(table_type, str):
        table_type = table_type.split(":", 1)[-1]
    dialect = "modern" if "random_sequence" in doc else "legacy"
    pools, missing = adapter._pools(doc)
    if not pools and table_type is None:
        missing.append("既无 pools 也无 type")
    payload = {
        "type": table_type,
        "dialect": dialect,
        "pools": pools,
        "random_sequence": doc.get("random_sequence"),
        "table": _table_id(file_label),
    }
    return payload, missing


def loot_roots() -> list[tuple[Path, Path]]:
    """`(loot_table 目录, 相对基准目录)` 列表。

    只看同步下来的**合并结果**：地形包覆盖已由上游合进 `datapack-merged/`，
    本仓库不再保留包原件，也没有第二层要叠。
    """
    out: list[tuple[Path, Path]] = []
    merged = paths.loot_tables(PACK)
    if merged.path.is_dir():
        out.append((merged.path, merged.path.parents[3]))
    return out


def main() -> int:
    adapter = LootAdapter()
    checked = 0
    diffs: list[str] = []

    for root, base in loot_roots():
        for path in sorted(root.rglob("*.json")):
            file_label = path.relative_to(base).as_posix()
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(doc, dict):
                continue
            file_label = path.relative_to(base).as_posix()
            want, want_missing = original_payload(adapter, doc, file_label)
            table = shared.normalize_table(doc, shared.table_id_from_file(file_label))
            got = shared.fact_payload(table)
            checked += 1
            a = json.dumps(want, ensure_ascii=False)
            b = json.dumps(got, ensure_ascii=False)
            if a != b:
                diffs.append(f"{file_label}\n  RA    : {a[:500]}\n  shared: {b[:500]}")
            elif list(table.missing) != want_missing:
                diffs.append(
                    f"{file_label} (missing 列表不同)\n"
                    f"  RA    : {want_missing}\n  shared: {list(table.missing)}"
                )

    print(f"checked={checked} diffs={len(diffs)}")
    if diffs:
        out = ROOT / "build" / "loot-parity.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n\n".join(diffs), encoding="utf-8")
        print(out)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
