"""核实红石/金锭里哪些硬编码常量确实能从上游数据取到。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bingo_grading import paths  # noqa: E402
from bingo_grading.loot.tables import load  # noqa: E402

lines: list[str] = []


def say(text: str = "") -> None:
    lines.append(text)


def name_of(spec: object) -> str:
    if isinstance(spec, dict):
        return str(spec.get("id") or spec.get("tag") or spec.get("item") or spec)
    return str(spec)


# ---------------------------------------------------------------- trade.jsonl
trade_path = paths.recipe_analysis("26.3").path / "facts" / "trade.jsonl"
say(f"== trade.jsonl：{trade_path.name}")
wanted = {("farmer", 1), ("mason", 1), ("cleric", 1)}
for raw in trade_path.read_text(encoding="utf-8").splitlines():
    if not raw.strip():
        continue
    doc = json.loads(raw)
    payload = doc.get("payload") or {}
    key = (payload.get("profession"), payload.get("level"))
    if key not in wanted:
        continue
    wants = payload.get("wants") or {}
    gives = payload.get("gives") or {}
    meta = payload.get("meta") or {}
    say(
        f"  {str(payload.get('profession')):<8}L{payload.get('level')} "
        f"{str(payload.get('trade')):<42}"
        f"wants={name_of(wants)}x{wants.get('count')} "
        f"gives={name_of(gives)}x{gives.get('count')} "
        f"max_uses={meta.get('max_uses')}"
    )

# ---------------------------------------------------------------- 方块掉落
say("")
say("== 原版方块掉落表（决定每块矿掉几个）")
vanilla = paths.loot_tables("26.3")
tables = load([vanilla.path])
for block in (
    "minecraft:blocks/redstone_ore",
    "minecraft:blocks/deepslate_redstone_ore",
    "minecraft:blocks/nether_gold_ore",
    "minecraft:blocks/gold_ore",
):
    if block not in tables:
        say(f"  {block:<44} 表不存在")
        continue
    doc = tables.require(block)

    def walk(entries: list, depth: int = 0) -> None:
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for child in entry.get("children") or []:
                if isinstance(child, dict):
                    walk([child], depth + 1)
            item = entry.get("name")
            if not item:
                continue
            counts = []
            for function in entry.get("functions") or []:
                if not isinstance(function, dict):
                    continue
                func = str(function.get("function", ""))
                if func.endswith("set_count"):
                    counts.append(
                        f"{function.get('count') if 'count' in function else ''}"
                        f"{function.get('min', '')}-{function.get('max', '')}"
                    )
            flag = "silk" if entry.get("conditions") else ""
            say(
                f"  {block:<44} {str(item).replace('minecraft:', ''):<20}"
                f"count={','.join(counts) or '1'} {flag}"
            )

    for pool in doc.get("pools") or []:
        walk(pool.get("entries") or [])

# ---------------------------------------------------------------- recipe.jsonl
say("")
say("== recipe.jsonl：金粒/金块/干草块/粘土块的折算")
recipe_path = paths.recipe_analysis("26.3").path / "facts" / "recipe.jsonl"
targets = {
    "minecraft:gold_ingot",
    "minecraft:hay_block",
    "minecraft:clay",
}
for raw in recipe_path.read_text(encoding="utf-8").splitlines():
    if not raw.strip():
        continue
    doc = json.loads(raw)
    payload = doc.get("payload") or {}
    result = payload.get("result") or {}
    rid = result.get("id") if isinstance(result, dict) else None
    if rid not in targets:
        continue
    ingredients = payload.get("ingredients") or payload.get("input") or []
    counts = []
    for item in ingredients if isinstance(ingredients, list) else []:
        if isinstance(item, dict):
            counts.append(f"{name_of(item)}x{item.get('count', 1)}")
        elif isinstance(item, list):
            counts.append(f"[{len(item)} 选 1]")
    say(
        f"  {str(payload.get('recipe') or payload.get('id') or doc.get('prov')):<52}"
        f"→ {rid}x{result.get('count', 1)}  from {counts}"
    )

out = ROOT / "build" / "data-availability.txt"
out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print(f"written {out}")
