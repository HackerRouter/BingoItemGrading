"""探查 gold_ingot 的来源：熔炼、交易、猪灵以物易物。"""

from __future__ import annotations

import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
facts = root / "ref" / "RecipeAnalysis" / "output" / "26.3" / "facts"

TARGETS = ("minecraft:gold_ingot", "minecraft:raw_gold", "minecraft:gold_nugget")


def rows(name: str):
    path = facts / name
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            yield json.loads(line)


def show_gold_trade() -> None:
    print("== trade.jsonl 中与 gold 相关 ==")
    count = 0
    for row in rows("trade.jsonl"):
        text = json.dumps(row, ensure_ascii=False)
        if "gold" not in text:
            continue
        count += 1
        if count <= 6:
            print(json.dumps(row, ensure_ascii=False)[:600])
    print("  命中", count)


def show_gold_recipe() -> None:
    print("\n== recipe.jsonl 中产出 gold_ingot 的条目 ==")
    for row in rows("recipe.jsonl"):
        out = json.dumps(row.get("output") or row.get("result") or {}, ensure_ascii=False)
        if "gold_ingot" not in out:
            continue
        print(json.dumps(row, ensure_ascii=False)[:700])


def show_keys() -> None:
    print("\n== 各文件第一条的键 ==")
    for name in ("recipe.jsonl", "trade.jsonl", "block_transform.jsonl"):
        first = next(rows(name), None)
        print(f"{name}: {list(first) if first else None}")


show_keys()
show_gold_trade()
show_gold_recipe()
