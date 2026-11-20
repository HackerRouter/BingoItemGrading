"""挖掘事实：方块硬度、工具要求、破坏时间。

数据全部来自上游 `facts/mining.jsonl` 与 `mining_tool_materials.jsonl`
（`bg data sync` 落到 `data/upstream/<pack>/recipe-analysis/`），本模块只做查表与换算。
**没有手写方块时长表**：曾经的 `BLOCK_BREAK_SECONDS` 五条是「铁器速度」的手抄，
与前置工具脱钩（成本按铁镐算、前置里却没有镐）。

## 原版公式

```
break_seconds = hardness × (1.5 正确工具 / 5.0 错误或徒手) / 工具速度
```

## 三条项目特化（数值在 `gamedata.py`）

1. **前置工具用木制**：`requires_correct_tool` 的方块挂木镐/木锹/木斧/木锄。
   木制工具只依赖木板与木棍，是工具链的自举起点；挂石镐会让
   「石镐 → 圆石 → 石镐」成环，整条挖矿路线判不可行。
   `needs_iron_tool` / `needs_diamond_tool` 的方块例外——木制工具对它们零掉落，
   必须给对应等级（钻石矿 → 铁镐，黑曜石 → 钻石镐）。
2. **破坏速度默认按石质工具**（`MINING_SPEED_MATERIAL`）：前置虽然是木制，
   速度取石质档——否则早期方块会被木镐速度罚一遍，与「玩家拿到石头就会换石镐」不符。
3. **地下开矿模型按铁质工具**（`UNDERGROUND_MINING_MATERIAL`）：矿道/洞穴模型假设
   玩家已经进入铁器阶段（挖矿道的成本主要不是单块速度，而是挖穿岩层的方块数）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import gamedata, paths
from .tags import TagSet, load as load_tags

BLOCK_REGISTRY = "minecraft:block"

# 工具类别 → 工具名后缀（`pickaxe` → `minecraft:wooden_pickaxe`）。
TOOL_CLASSES = ("pickaxe", "axe", "shovel", "hoe")

# 材质 → 等级序（只用于取「不低于方块要求」的材质）。
MATERIAL_ORDER = ("wood", "stone", "iron", "diamond", "netherite")

# 「必须该等级以上才有掉落」的标签 → 材质。
NEEDS_LABELS = {
    "minecraft:needs_stone_tool": "stone",
    "minecraft:needs_iron_tool": "iron",
    "minecraft:needs_diamond_tool": "diamond",
}

# 基础石头（三个维度的 9 个方块）：stone/deepslate/andesite/diorite/granite/
# tuff/netherrack/basalt/blackstone。只用于诊断（`BlockMining.base_stone`），
# 工具前置改用「`requires_correct_tool` 且要镐」判定，见 `tool_for`。
BASE_STONE_LABELS = (
    "minecraft:base_stone_overworld",
    "minecraft:base_stone_nether",
    "minecraft:base_stone_end",
)

# 材质 → 工具物品名前缀。`wood` 的工具叫 **`wooden`**_pickaxe，
# 拼错成 `wood_pickaxe` 会让工具前置指向一个不存在的物品——分层把它判成
# `no_rule`，于是所有石头类的挖矿路线都静默消失（tuff 改走 602 秒的结构路线）。
TOOL_ITEM_PREFIX = {
    "wood": "wooden",
    "gold": "golden",
    "stone": "stone",
    "copper": "copper",
    "iron": "iron",
    "diamond": "diamond",
    "netherite": "netherite",
}


def _tool_item(material: str, tool_class: str) -> str:
    prefix = TOOL_ITEM_PREFIX.get(material, material)
    return f"minecraft:{prefix}_{tool_class}"


class MiningFactsError(ValueError):
    """挖掘事实不可用（缺文件、结构不认识）。"""


@dataclass(frozen=True)
class BlockMining:
    """一个方块的挖掘属性。"""

    hardness: float
    requires_correct_tool: bool
    tool_class: str | None
    min_material: str | None
    base_stone: bool = False


@dataclass
class MiningFacts:
    """方块 → 挖掘属性 + 材质速度。"""

    blocks: dict[str, BlockMining] = field(default_factory=dict)
    speeds: dict[str, float] = field(default_factory=dict)
    _tags: TagSet = field(default_factory=TagSet)

    # -------------------------------------------------------------- 查询
    def of(self, block: str) -> BlockMining:
        """方块属性；未知方块按「徒手、硬度 0」处理。

        `block` 可以是裸名（`stone`）或全名（`minecraft:stone`）：调用方常年用裸名。
        """
        key = block if ":" in block else f"minecraft:{block}"
        return self.blocks.get(
            key,
            BlockMining(hardness=0.0, requires_correct_tool=False, tool_class=None, min_material=None),
        )

    def hardness(self, block: str) -> float:
        return self.of(block).hardness

    def known(self, block: str) -> bool:
        """上游是否登记过这个方块（裸名或全名）。"""
        key = block if ":" in block else f"minecraft:{block}"
        return key in self.blocks

    def tool_for(self, block: str) -> str | None:
        """该方块的前置工具；`None` 表示不给前置。

        只有两类方块挂前置：
        1. `needs_stone/iron/diamond_tool`——木制工具对它们零掉落，必须给对应等级；
        2. **石头类**（`requires_correct_tool` 且要鎬）——包括 `base_stone_*` 的 9 个基础石头
           与它们的变体（圆石、石砖、混凝土、陶瓦）：给木鎬自举。
           漏掉圆石会让 `mine:vein:cobblestone`（不需要鎬）比 `mine:vein:stone`（要鎬）
           便宜，整条石头链都改走那条不存在的“徒手挖圆石”。

        斧/锹/锄类（木头、泥土、沙子）即使要求正确工具也不挂——那些是顺手挖的。
        """
        info = self.of(block)
        if info.min_material in ("stone", "iron", "diamond", "netherite"):
            return _tool_item(info.min_material, info.tool_class or "pickaxe")
        if info.requires_correct_tool and info.tool_class == "pickaxe":
            return _tool_item("wood", "pickaxe")
        return None

    def break_seconds(
        self, block: str, *, material: str | None = None, fallback: str | None = None
    ) -> float:
        """破坏一个方块的秒数。

        `material` 不给时按 `grade_of()`（项目特化：默认石质，圆石链木质）；
        地下开矿模型显式传 `gamedata.UNDERGROUND_MINING_MATERIAL`。
        `fallback`：上游没登记这个方块时用它代替（旧代码的 `dict.get(block, 默认)`）；
        不给时按 0 秒——只对真正瞬间破坏的方块合理。
        """
        if not self.known(block):
            if fallback is None:
                return 0.0
            block = fallback
        info = self.of(block)
        if info.hardness <= 0.0:
            return 0.0
        if info.tool_class is None:
            # 没有对应工具类：徒手，且永远是 5 倍系数。
            return info.hardness * 5.0
        grade = material or self.grade_of(block)
        # 材质不能低于方块自身要求（石镐挖不动钻石矿）。
        grade = self._at_least(grade, info.min_material)
        speed = self.speeds.get(grade, 1.0)
        return info.hardness * 1.5 / speed

    def grade_of(self, block: str) -> str:
        """破坏速度用哪一档工具材质（项目特化，见模块 docstring）。"""
        info = self.of(block)
        if info.min_material is not None:
            return info.min_material
        if info.requires_correct_tool and info.tool_class == "pickaxe":
            # 石头类的前置是木鎬（自举），速度也按木制档。
            return "wood"
        return gamedata.MINING_SPEED_MATERIAL

    # -------------------------------------------------------------- 内部
    def _tool_material(self, info: BlockMining) -> str:
        """前置工具的材质：无 `needs_*` 要求时给木制（自举），否则按方块要求升级。

        圆石只要求「用镐」不要求等级 → 木镐；深板岩要求石镐 → 石镐。
        木镐依赖木板与木棍，是唯一不依赖圆石的起点，所以不会成环。
        """
        return info.min_material or "wood"

    @staticmethod
    def _at_least(material: str, minimum: str | None) -> str:
        if minimum is None:
            return material
        try:
            if MATERIAL_ORDER.index(material) >= MATERIAL_ORDER.index(minimum):
                return material
        except ValueError:
            return material
        return minimum


def _tool_class(tags: TagSet, block: str) -> str | None:
    for name in TOOL_CLASSES:
        if block in tags.expand(f"minecraft:mineable/{name}", registry=BLOCK_REGISTRY):
            return name
    return None


def _min_material(tags: TagSet, block: str) -> str | None:
    for label, material in NEEDS_LABELS.items():
        if block in tags.expand(label, registry=BLOCK_REGISTRY):
            return material
    return None


def _is_base_stone(tags: TagSet, block: str) -> bool:
    for label in BASE_STONE_LABELS:
        if block in tags.expand(label, registry=BLOCK_REGISTRY):
            return True
    return False


@lru_cache(maxsize=8)
def load(pack: str | None = None, override: str | None = None) -> MiningFacts:
    """读上游挖掘事实。文件缺失时返回空集合（调用方按「无数据」处理）。"""
    label = pack or _default_pack()
    mining_path = paths.mining_facts(label, override).path
    speeds_path = paths.mining_tool_materials(label, override).path
    tags_path = paths.tag_facts(label, override).path
    if not mining_path.exists():
        return MiningFacts()
    speeds = _read_speeds(speeds_path)
    tags = load_tags(tags_path)

    blocks: dict[str, BlockMining] = {}
    with mining_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line).get("payload") or {}
            block = payload.get("block")
            if not isinstance(block, str):
                continue
            blocks[block] = BlockMining(
                hardness=float(payload.get("hardness") or 0.0),
                requires_correct_tool=bool(payload.get("requires_correct_tool")),
                tool_class=_tool_class(tags, block),
                min_material=_min_material(tags, block),
                base_stone=_is_base_stone(tags, block),
            )
    return MiningFacts(blocks=blocks, speeds=speeds, _tags=tags)


def break_seconds(
    block: str,
    *,
    material: str | None = None,
    fallback: str | None = None,
    pack: str | None = None,
) -> float:
    """便利函数：破坏一个方块的秒数。`material` 不给时按项目特化档。"""
    return load(pack).break_seconds(block, material=material, fallback=fallback)


def tool_for(block: str, *, pack: str | None = None) -> str | None:
    """便利函数：该方块的前置工具；`None` 表示徒手也能拿到。"""
    return load(pack).tool_for(block)


def _default_pack() -> str:
    """默认数据包：`data/upstream/` 下的包目录（通常只有一个）。"""
    root = paths.UPSTREAM_ROOT
    if not root.exists():
        raise MiningFactsError(f"上游目录不存在：{root}")
    packs = sorted(p.name for p in root.iterdir() if p.is_dir())
    if not packs:
        raise MiningFactsError(f"{root} 下没有数据包目录")
    return packs[-1]


def _read_speeds(path: Path) -> dict[str, float]:
    speeds: dict[str, float] = {}
    if not path.exists():
        return speeds
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            material = row.get("material")
            speed = row.get("speed")
            if isinstance(material, str) and isinstance(speed, (int, float)):
                speeds[material] = float(speed)
    return speeds
