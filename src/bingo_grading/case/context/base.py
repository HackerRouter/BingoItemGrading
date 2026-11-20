"""`CaseContext`：取数唯一入口。字段与 `load` 在这里，其余方法按族拆成 mixin。"""

from __future__ import annotations


from dataclasses import dataclass, field
from pathlib import Path
from bingo_grading.stats import store as stats_store

from .recipes import RecipesMixin
from .exposure import ExposureMixin
from .mining import MiningMixin
from .structures import StructuresMixin
from .patches import PatchesMixin
from .content import ContentMixin
from .loot import LootMixin
from .biomes import BiomesMixin
from .mobs import MobsMixin
from .model import CaseError

@dataclass
class CaseContext(RecipesMixin, ExposureMixin, MiningMixin, StructuresMixin, PatchesMixin, ContentMixin, LootMixin, BiomesMixin, MobsMixin):
    """案例可用的数据面。缺失时返回 None，由案例决定怎么退化。"""


    store: object


    dimension: str = "minecraft:overworld"


    notes: list[str] = field(default_factory=list)


    # 下面两个是缓存：`pack_versions` 与 `mining` 都要扫全量行（几千条），
    # 工具链递归估值时会重复问同一批物品，不缓存就是 O(行数) × 递归次数。
    _pack_version: str | None = field(default=None, repr=False, compare=False)


    _mining_cache: dict = field(default_factory=dict, repr=False, compare=False)


    _mob_spawn_cache: dict = field(default_factory=dict, repr=False, compare=False)


    # 配方事实按 pack 缓存：`_recipe_index` 要读几份 jsonl，构建全库时会被问上千次。
    _recipe_cache: dict = field(default_factory=dict, repr=False, compare=False)


    # 维度判定（方块 / 结构）按名字缓存：内部扫一遍行，结果与上下无关。
    _dimension_cache: dict = field(default_factory=dict, repr=False, compare=False)


    # 「哪些结构变体有模板行」的全集：`structure_block_sources` 每次调用都要它。
    _templated_cache: frozenset | None = field(default=None, repr=False, compare=False)


    @classmethod
    def load(cls, path: Path, dimension: str = "minecraft:overworld") -> "CaseContext":
        return cls(store=stats_store.load(path), dimension=dimension)


    # ---------------------------------------------------------------- 配方事实

    def pack_version(self) -> str:
        """快照对应的地形包版本（配方事实按它去找上游目录）。"""
        if self._pack_version is not None:
            return self._pack_version
        versions = sorted(self.store.pack_versions())
        if not versions:
            raise CaseError("统计快照没有任何 pack_version，无法确定地形包版本")
        value = versions[-1]
        self._pack_version = value
        return value
