"""盘点硬编码常数能否被现有数据替换。

逐条检查：方块掉落数、交易条款、配方换算、结构拼接。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bingo_grading.loot.expect import expect  # noqa: E402
from bingo_grading.loot.tables import load as load_tables  # noqa: E402

root = Path(__file__).resolve().parents[1]
facts = root / "ref" / "RecipeAnalysis" / "output" / "26.3" / "facts"
data = root / "ref" / "RecipeAnalysis" / "inputs" / "26.3" / "data"

lines: list[str] = []


def say(text: str = "") -> None:
    lines.append(text)


# ------------------------------------------------------------ 1. 方块掉落
say("== 1. 方块掉落数量（代码里硬编码 4.5 / 4.0）==")
base = data / "minecraft" / "loot_table" / "blocks"
pack = root / "ref" / "WorldGenStatsCollector" / ".server"
tables = load_tables([p for p in (base, pack) if p.exists()])
say(f"  加载 loot_table 目录: {base.exists()}, 共 {len(tables)} 张表")

for block in (
    "minecraft:redstone_ore",
    "minecraft:deepslate_redstone_ore",
    "minecraft:nether_gold_ore",
    "minecraft:gold_ore",
    "minecraft:deepslate_gold_ore",
    "minecraft:emerald_ore",
    "minecraft:coal_ore",
):
    table_id = f"{block}:blocks"
    # 表的实际 ID 形态：minecraft:blocks/redstone_ore
    candidates = [f"minecraft:blocks/{block.split(':', 1)[1]}"]
    hit = None
    for candidate in candidates:
        if candidate in tables.tables:
            hit = candidate
            break
    if hit is None:
        say(f"  {block:<34} 找不到掉落表（试过 {candidates}）")
        continue
    result = expect(hit, tables, tool_probability=1.0)
    say(f"  {block:<34} → {result.per_item}  总 {result.total_items:.3f} 个/块")


# ------------------------------------------------------------ 2. 交易条款
say("\n== 2. 交易条款（代码里硬编码 20 小麦 / 12 次 / 16 次）==")
for line in (facts / "trade.jsonl").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line:
        continue
    payload = (json.loads(line).get("payload") or {})
    wants = payload.get("wants") or {}
    gives = payload.get("gives") or {}
    if not wants.get("id") or not gives.get("id"):
        continue
    label = f"{wants.get('count')}x{wants.get('id')} -> {gives.get('count')}x{gives.get('id')}"
    if label in (
        "20xminecraft:wheat -> 1xminecraft:emerald",
        "10xminecraft:clay_ball -> 1xminecraft:emerald",
        "1xminecraft:emerald -> 2xminecraft:redstone",
    ):
        meta = payload.get("meta") or {}
        say(f"  {payload.get('profession'):<10} lv{payload.get('level')}  "
            f"{label:<52} max_uses={meta.get('max_uses')}")


# ------------------------------------------------------------ 3. 配方换算
say("\n== 3. 配方换算（代码里硬编码 9 粒=1 锭、1 干草=9 麦）==")
WANT = {
    "minecraft:gold_ingot",
    "minecraft:hay_block",
    "minecraft:clay",
}
for line in (facts / "recipe.jsonl").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line:
        continue
    payload = (json.loads(line).get("payload") or {})
    result = payload.get("result") or {}
    if result.get("id") not in WANT:
        continue
    serializer = payload.get("serializer", "")
    if "nugget" in json.dumps(payload, ensure_ascii=False) or "wheat" in json.dumps(payload, ensure_ascii=False) or "clay" in json.dumps(payload, ensure_ascii=False):
        prov = (json.loads(line).get("prov") or {}).get("file", "")
        if any(k in prov for k in ("gold_ingot_from_nuggets", "hay_block", "clay")):
            say(f"  {prov:<62} -> {result.get('count')}x{result.get('id')}  ({serializer})")


# ------------------------------------------------------------ 4. 村庄拼接
say("\n== 4. 村庄箱数（代码里硬编码 10 箱/村）==")
pooled = 0
with_chest = 0
for line in (facts / "template.jsonl").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line:
        continue
    payload = (json.loads(line).get("payload") or {})
    template = payload.get("template")
    if not isinstance(template, str) or not template.startswith("village/"):
        continue
    pooled += 1
    if payload.get("loot_tables"):
        with_chest += 1
say(f"  村庄模板 {pooled} 个，其中有箱子的 {with_chest} 个")
say("  模板行有 jigsaw_pools 字段，可推出「一个村庄由哪些建筑拼成」")

text = "\n".join(lines) + "\n"
out = root / "build" / "data-source-audit.txt"
out.write_text(text, encoding="utf-8", newline="\n")
print(f"written {out}")
