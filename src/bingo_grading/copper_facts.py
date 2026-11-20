"""铜质方块的自然氧化链。

上游 `facts/block_transform.jsonl` 记的是**玩家动手**的变换（斧头除锈/脱蜡、
锹压平、锄耕地）。自然氧化本身不在里面——那是随机刻机制。但「除锈对」反向
就是「氧化对」，所以从这份事实反推每一族的氧化顺序，不必手写二十多条。

方向约定：数据里 `from` 是**更锈**的一方（`exposed_copper_bars`），
`to` 是更不锈的一方（`copper_bars`）——斧头用来除锈。所以
`child_of[更锈] = 更不锈`，沿它向上走就得到阶段号。

**涂蜡变种不参与自然氧化**（打蜡就是防腐），它们的来源是「对应未涂蜡变种 +
蜜脾」的配方，那条路已经由配方事实给出。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from . import paths

AXE = "minecraft:axe"
BLOCK_PREFIX = "block:minecraft:"
WAXED = "waxed_"
MAX_STAGE = 3

# 氧化变种的名字前缀。铜质方块里只有 `lightning_rod` / `copper_golem_statue`
# 这类名字不带 `copper`，靠前缀认；而木头去皮、除草的锄头变换名字里
# 既没有 `copper` 也不带氧化前缀，因此不会被误收。
OXIDE_PREFIXES = ("exposed_", "weathered_", "oxidized_")


def _is_copper(name: str) -> bool:
    short = name.partition("minecraft:")[2]
    return "copper" in short or short.startswith(OXIDE_PREFIXES)


@dataclass(frozen=True)
class Oxidation:
    """一个氧化变种从哪来。"""

    previous: str
    """更不锈的同族方块（上一阶段）。"""

    stage: int
    """1 = 未氧化 → 斑驳，2 = 斑驳 → 锈蚀，3 = 锈蚀 → 氧化。"""


def _block_name(value: object) -> str | None:
    """`["block:minecraft:exposed_copper"]` → `minecraft:exposed_copper`。"""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if not isinstance(value, str):
        return None
    _, sep, rest = value.partition(BLOCK_PREFIX)
    return f"minecraft:{rest}" if sep and rest else None


def _default_pack() -> str:
    root = paths.UPSTREAM_ROOT
    packs = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.exists() else []
    return packs[-1] if packs else ""


@lru_cache(maxsize=8)
def load(pack: str | None = None, override: str | None = None) -> dict[str, Oxidation]:
    """氧化变种 → `Oxidation`。文件缺失时返回空表（调用方按「无数据」处理）。"""
    label = pack or _default_pack()
    if not label:
        return {}
    path = paths.block_transform_facts(label, override).path
    if not path.exists():
        return {}

    # `{更锈: 更不锈}`，只收斧头、且两边都不是涂蜡变种。
    child_of: dict[str, str] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line).get("payload") or {}
            if payload.get("transformer") != AXE:
                continue
            rusty = _block_name(payload.get("from"))
            fresh = _block_name(payload.get("to"))
            if not rusty or not fresh:
                continue
            if WAXED in rusty or WAXED in fresh:
                continue
            if not _is_copper(rusty):
                # 斧头还能去皮、除草…那些不是氧化，方向也不同。
                continue
            child_of.setdefault(rusty, fresh)

    result: dict[str, Oxidation] = {}
    for rusty, fresh in child_of.items():
        stage = 1
        cursor = fresh
        # 链最长 3 级；`guard` 防数据里出现环（脱蜡 + 除锈混在一起时会绕回来）。
        for _ in range(MAX_STAGE):
            if cursor not in child_of:
                break
            cursor = child_of[cursor]
            stage += 1
        result[rusty] = Oxidation(previous=fresh, stage=min(stage, MAX_STAGE))
    return result
