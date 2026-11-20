"""核对 trail_ruins 的可刷扫点：模板事实 vs 容器导出 vs 采集侧实测。

回答三个数：
- 模板里 `suspicious_*` 方块的实际个数（`template.jsonl` 的 `block_counts`）
- `template_containers.jsonl` 为这些模板导出了多少行
- 采集侧实测每个实例多少张考古表
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RA = ROOT / "data" / "upstream" / "26.3" / "recipe-analysis"
RUN = sorted((ROOT / "data" / "upstream" / "26.3" / "worldgen-stats").iterdir())[-1]
OUT = ROOT / "build" / "trail-ruins.txt"
STRUCTURE = "minecraft:trail_ruins"
SUSPICIOUS = ("minecraft:suspicious_sand", "minecraft:suspicious_gravel")


def main() -> None:
    facts = {}
    for line in (RA / "facts" / "template.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            payload = json.loads(line)["payload"]
            facts[payload["template"]] = payload

    rows_per_template: dict[str, int] = {}
    for line in (RA / "export" / "template_containers.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("block_entity") in SUSPICIOUS:
            rows_per_template[row["template"]] = rows_per_template.get(row["template"], 0) + 1

    payload = json.loads((RUN / "structure-interior.overworld.json").read_text(encoding="utf-8"))
    entry = next(
        item
        for item in payload["result"]["minecraft:overworld"]["structures"]
        if item["structure"] == STRUCTURE
    )
    placed = [(e["template"].split(":", 1)[-1], float(e.get("perStart") or 0)) for e in entry["templates"]]

    lines = [
        f"{STRUCTURE}: 放置模板 {len(placed)}，实例 {entry['starts']}，片段/实例 {entry['piecesPerStart']:.1f}",
        f"实测考古表/实例 {sum((entry.get('lootTables') or {}).values()) / entry['starts']:.1f}",
        "",
        f"{'模板':<52}{'block_counts':>14}{'导出行':>8}{'perStart':>10}",
    ]
    weighted_facts = 0.0
    weighted_rows = 0.0
    total_pieces = 0.0
    for name, per_start in sorted(placed, key=lambda pair: -pair[1]):
        total_pieces += per_start
        counted = 0
        counts = (facts.get(name) or {}).get("block_counts") or {}
        for key, amount in counts.items():
            base = key.split("{", 1)[0]
            if base in SUSPICIOUS:
                counted += amount
        exported = rows_per_template.get(name, 0)
        weighted_facts += counted * per_start
        weighted_rows += exported * per_start
        if counted or exported:
            lines.append(f"{name:<52}{counted:>14}{exported:>8}{per_start:>10.2f}")

    lines.append("")
    lines.append(f"片段合计/实例 {total_pieces:.1f}")
    lines.append(f"按 block_counts 加权：每实例 {weighted_facts:.1f} 个可疑方块")
    lines.append(f"按导出行加权：每实例 {weighted_rows:.1f} 行")
    lines.append(f"采集侧实测：每实例 {sum((entry.get('lootTables') or {}).values()) / entry['starts']:.1f} 张考古表")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
