"""比对统计产物的结构集合与来源索引的战利品表路径，找出映射缺口。

输出写 UTF-8 文件。只读，不改任何东西。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    stats_dir = Path(sys.argv[1])
    out = Path(sys.argv[2])

    spacing = json.loads((stats_dir / "structure-spacing.json").read_text(encoding="utf-8"))
    biomes = json.loads((stats_dir / "biome-histogram.json").read_text(encoding="utf-8"))
    ores = json.loads((stats_dir / "ore-exposure.json").read_text(encoding="utf-8"))
    lava = json.loads((stats_dir / "lava-lakes.json").read_text(encoding="utf-8"))

    lines: list[str] = []

    lines.append("== structure-spacing groups")
    for group in spacing["result"]["groups"]:
        ids = group.get("structureIds") or []
        lines.append(
            f"{group['set']:<44} count={group['count']:>4} "
            f"spacing={group.get('configured', {}).get('spacingChunks')} "
            f"sep={group.get('configured', {}).get('separationChunks')} "
            f"meanNN={group.get('meanNNBlocks')} ids={ids}"
        )

    lines.append("\n== surface biomes (share>=0.5)")
    for biome in biomes["result"]["surface"]["biomes"]:
        if biome["share"] >= 0.5:
            lines.append(f"{biome['id']:<44} {biome['share']:>7.3f}%")

    lines.append("\n== underground biomes (top 12)")
    for biome in biomes["result"]["underground"]["biomes"][:12]:
        lines.append(f"{biome['id']:<44} {biome['share']:>7.3f}%")
    lines.append(
        f"columns={biomes['result']['underground']['columns']} "
        f"sameAsSurface={biomes['result']['underground']['sameAsSurface']}"
    )

    lines.append("\n== ore byOre")
    for ore, data in ores["result"]["byOre"].items():
        lines.append(
            f"{ore:<40} total={data['avgTotal']:<8} air={data['avgAirExposed']:<8} "
            f"water={data['avgWaterExposed']:<7} buried={data['avgBuried']:<8} "
            f"airPct={data['airPct']:<7} waterPct={data['waterPct']}"
        )
    lines.append(f"chunks={ores['result']['chunks']} perChunk={ores['result']['perChunk']}")

    lines.append("\n== ore sections (yRange, chunks, per-ore totals)")
    for key, section in sorted(ores["result"]["sections"].items(), key=lambda kv: int(kv[0])):
        tops = sorted(
            ((ore.split(":", 1)[1], cell["avgTotal"]) for ore, cell in section["byOre"].items()),
            key=lambda kv: -kv[1],
        )[:3]
        lines.append(f"sec {section['section']:>3} y{section['yRange']} chunks={section['chunks']:<6} top={tops}")

    lines.append("\n== lava lakes")
    surface = lava["result"]["surface"]
    lines.append(f"lakes={surface['lakes']} groups={surface['groups']}")
    lines.append(f"spacing={surface['spacing']}")
    lines.append(f"density={surface['density']}")
    lines.append(f"landWater={surface['landWater']}")
    lines.append(f"underground={lava['result']['underground']}")

    # 来源索引里的战利品表 subject
    index_path = ROOT / "build" / "26.3" / "source_index.jsonl"
    lines.append("\n== source_index loot_table subjects")
    subjects: Counter = Counter()
    if index_path.exists():
        for line in index_path.read_text(encoding="utf-8").splitlines()[1:]:
            record = json.loads(line)
            if record["source_type"] == "loot_table":
                subjects[record["subject"]] += 1
    for subject, count in subjects.most_common():
        lines.append(f"{count:>4}  {subject}")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{out}  {out.stat().st_size} bytes, {len(lines)} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
