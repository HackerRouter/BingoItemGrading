"""检查结构模板 NBT 里的容器与战利品表，用于判断缺口在哪一侧。

用法：python tools/check_template_nbt.py <结构前缀> [--cache <目录>]
输出写到 build/template-nbt.txt。
"""

from __future__ import annotations

import gzip
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = ROOT / "ref" / "RecipeAnalysis" / ".cache" / "server-a14df142f923" / "structures" / "data" / "minecraft" / "structure"
OUT = ROOT / "build" / "template-nbt.txt"

CONTAINERS = (
    b"minecraft:chest",
    b"minecraft:barrel",
    b"minecraft:trapped_chest",
    b"minecraft:dispenser",
    b"minecraft:vault",
    b"minecraft:suspicious_sand",
    b"minecraft:suspicious_gravel",
)


def main(argv: list[str]) -> int:
    prefix = argv[1] if len(argv) > 1 else "ancient_city"
    base = Path(argv[3]) if len(argv) > 3 and argv[2] == "--cache" else DEFAULT_CACHE
    root = base / prefix
    if not root.is_dir():
        print(f"目录不存在：{root}")
        return 1

    files = sorted(p for p in root.rglob("*") if p.is_file())
    lines = [f"# {root}", f"文件总数：{len(files)}", ""]
    with_container: list[tuple[str, list[str]]] = []
    for path in files:
        raw = path.read_bytes()
        data = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
        hits = [name.decode() for name in CONTAINERS if name in data]
        if b"LootTable" in data:
            hits.append("LootTable")
        if hits:
            with_container.append((path.relative_to(root).as_posix(), hits))

    lines.append(f"含容器/战利品表标记的模板：{len(with_container)}")
    for name, hits in with_container:
        lines.append(f"  {name:<60} {hits}")
    lines.append("")
    loot_only = [name for name, hits in with_container if "LootTable" in hits]
    lines.append(f"其中带 LootTable 的模板：{len(loot_only)}")
    for name in loot_only[:40]:
        lines.append(f"  {name}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
