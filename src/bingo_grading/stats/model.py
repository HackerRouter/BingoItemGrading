"""`world_stat` 行的形状与校验。

主键是七元组 `(pack_version, scope_level, dimension, biome, stat_type, subject, condition)`。
不适用的分层字段填空串而不是 `null`：空串可以让主键直接用元组比较，
`null` 会让同一行在不同写法下不相等。

`value` 按 `stat_type` 有固定的键集合。多一个键、少一个键都报错：
统计层的下游是数值聚合，静默忽略字段会得到「看起来正常但缺一项分量」的结果。
"""

from __future__ import annotations

from dataclasses import dataclass, field

SCOPE_LEVELS = ("global", "dimension", "biome", "biome_subject")

# 回退顺序：细层在前，粗层在后。
SCOPE_ORDER = ("biome_subject", "biome", "dimension", "global")

CONFIDENCE_LEVELS = ("high", "medium", "low")

# `stat_type` → `value` 的键集合。`required` 缺一即错，`optional` 允许缺省。
#
# 可选键都是为了容纳实测数据里存在、但第一版引擎并不需要的分量
# （纵向分布、结构变体）。缺省即「没有测量值」，不得填零项充数。
STAT_VALUE_SCHEMA: dict[str, dict[str, tuple[str, ...]]] = {
    "ore_exposure": {
        "required": (
            "air_exposed",
            "water_exposed",
            "buried",
            "per_chunk_density",
            "air_exposed_share",
        ),
        "optional": ("by_section", "family", "variant_breakdown", "between_variant_variance"),
    },
    # 群系级只讲「分布」：玩家会专程进该群系挖矿道，暴露不影响代价。
    # 分母是「该群系等效区块数」，不是总区块数——两者不可混用。
    "ore_density": {
        "required": ("per_chunk_density",),
        "optional": (
            "equivalent_chunks",
            "chunks",
            "total_blocks",
            "reliable",
            "by_section",
            "variant_breakdown",
            "between_variant_variance",
        ),
    },
    # 非矿石方块的群系级密度（紫颂植物、黑曜石、原木等）。
    # 与 `ore_density` 同口径（群系等效区块），但上游把它归在 `bulk` 类：
    # 只数数量，不做暴露判定。
    "block_density": {
        "required": ("per_chunk_density",),
        "optional": (
            "equivalent_chunks",
            "chunks",
            "total_blocks",
            "reliable",
            "by_section",
            "variant_breakdown",
            "between_variant_variance",
        ),
    },
    "structure_density": {
        "required": ("expected_nearest_distance",),
        "optional": (
            "spacing",
            "separation",
            "biome_conditions",
            "structure_set",
            "structure_ids",
            "observations",
            "median_nearest_distance",
            "mean_size",
            "density_per_1000_chunks",
            # 最近邻距离的分布尾部。均值/中位数把非对称分布当对称处理，
            # 下游要在「期望 / 中位数 / 保守估计」之间切换就得看尾部。
            # 采集侧在样本不足时整批写 null（不写 0），这里允许缺省。
            "p25_nearest_distance",
            "p50_nearest_distance",
            "p75_nearest_distance",
            "p90_nearest_distance",
            "variance_nearest_distance",
            "min_nearest_distance",
            "max_nearest_distance",
            # `structure`（有 structure start）/ `feature`（placed feature，如沙漠水井）
            "source",
            "derived",
            "variant_breakdown",
            "between_variant_variance",
        ),
    },
    "biome_patch": {
        "required": (
            "patch_density",
            "mean_area",
            "area_variance",
            "area_fraction",
            "vertical_condition_prob",
        ),
        "optional": (
            "patches",
            "median_area",
            "max_area",
            "edge_touch",
            "neighbors",
            "autocorr_tier",
            "reliable",
            "variant_breakdown",
            "between_variant_variance",
        ),
    },
    # 一次「触发」的期望产出。触发方式由 `trigger` 说明：
    # `block_break` / `kill` / `chest_open` / `shear` / `brush`。
    # 所有直接来源（方块、生物、箱子、剪毛、刷扫）用同一口径，才能横向比较。
    "loot_expectation": {
        "required": ("per_trigger_expected", "trigger"),
        "optional": (
            "table",
            "chests_per_structure",
            "structure_frequency",
            # 每件物品一次触发的相对标准差（`sd / mean`）。来源是战利品表的
            # `rolls` 分布 / 条目权重 / `set_count` 分布；缺省即「按确定量处理」。
            "per_trigger_cv",
            "assumptions",
            "unsupported",
            "variant_breakdown",
            "between_variant_variance",
        ),
    },
    # 结构内容。`source=template` 来自结构模板（静态真值），`source=measured` 是采集侧实测。
    # 两者的分母不同（每模板 / 每起点），因此 `source` 是必需字段，不可混用。
    "structure_content": {
        "required": ("source", "containers", "loot_tables"),
        "optional": (
            "templates",
            "templates_with_containers",
            "templates_placed",
            "templates_matched",
            "containers_per_start",
            "containers_per_covered_chunk",
            "loot_tables_per_start",
            "starts",
            "blocks",
            "blocks_per_start",
            "spawners_per_start",
            "entities_per_start",
            # 从**结构定义**推出来的固定生成量（`STRUCTURE_SPAWNED`：每座海底神殿
            # 3 只远古守卫者）。与实测的 `entities_per_start` 分开存：前者是代码常量，
            # 后者是扫出来的，两者可信度不同，不能混在一起。
            "spawned_per_start",
            # 刷怪笼的「上限」类参数（`MaxNearbyEntities` / `SpawnCount` /
            # `SpawnRange` 的实测区间）。是产能上限，不是刷怪速率。
            "spawner_caps",
            "pieces_per_start",
            "volume_per_start",
            "kinds",
            # 地牢按锚点高度拆分（`shallow` y>=0 / `deep` y<0）。搜索成本只能
            # 用浅层那一组的间数，拿总数会把深板岩层的地牢也算进去。
            "by_depth",
            "block_kinds",
            "covered_chunks",
            # 采集器自己的区块分母。算「密度 → 期望最近距离」必须用它；
            # 借 `block_density` 的 `chunks` 是另一次扫描的范围，会算错。
            "chunks",
        ),
    },
    # 一个职业/等级的全部报价。多条等价交易都保留，由调用方选最便宜那条。
    "trade_offer": {
        "required": ("offers", "offer_count"),
        "optional": ("trades_ref",),
    },
    "spawn_distribution": {
        "required": ("biome_weights",),
        "optional": (
            "underground_biome_weights",
            "water_share",
            "variant_breakdown",
            "between_variant_variance",
        ),
    },
    "mob_density": {
        "required": ("per_chunk",),
        "optional": (
            "chunks_per",
            "groups_per_chunk",
            "avg_group_size",
            "avg_y",
            "category",
            "variant_breakdown",
            "between_variant_variance",
        ),
    },
    # 刷怪表的原始条目：某个 holder（群系 / 结构 / 袭击 / 刷怪笼）会刷什么、
    # 权重多少、每次刷几只。
    #
    # 与 `mob_density` 的区别：那个是**实测密度**（每区块几只），依赖玩家活动，
    # 敌对生物根本测不出来（C17 已撤回）；这个是**刷怪规则的静态事实**，
    # 能回答「在下界要塞里待一会儿会遇到几只凋灵骷髅」。
    # `condition` 写 `holder=<holder>`，因为同一生物在多个 holder 里各有一条。
    "mob_spawn": {
        "required": ("holder", "holder_kind"),
        "optional": (
            "weight",
            "count_min",
            "count_max",
            "category",
            "requires",
            "wave",
            "wave_counts",
        ),
    },
    # 任意方块的 6 面暴露分解（维度级）：天空空气 / 洞穴空气 / 水 / 埋着。
    #
    # 与 `ore_exposure` 的区别：那个只对矿石、而且 `air_exposed_share` 把
    # 洞穴空气混在一起（ADR 0014 记下了这个缺陷）。这里把天空与洞穴拆开，
    # 下游才能分「走过去捡」（sky/water）与「下洞穴挖」（cave）。
    "block_exposure": {
        "required": (
            "per_chunk_density",
            "sky_air_share",
            "cave_air_share",
            "water_share",
            "buried_share",
        ),
        "optional": (
            "air_exposed_share",
            "cave_share_of_air",
            "both_air_share",
            "unknown_share",
            "sample_blocks",
            "reliable",
            "variant_breakdown",
            "between_variant_variance",
        ),
    },
    # 逐纵段的实心占比（维度级，每维度一行）。    #
    # 它描述的是**段**，不是方块：`fill = avgTotal / 4096` 是段内实心方块占比，
    # `fill_dry` 再把水与岩浆扣掉。下游用它判断「某方块所在位置的上下是否敞开」，
    # 决定采集模型是走过去还是挖下去——所以段表必须能脱离具体方块查到。
    "section_fill": {
        "required": ("sections",),
        "optional": (
            "chunks",
            "variant_breakdown",
            "between_variant_variance",
        ),
    },
}

STAT_TYPES = tuple(STAT_VALUE_SCHEMA)

# 两类统计的查询方式不同，落盘也分两个文件：
#
# - `SPATIAL_TYPES`：可回退的空间测量。按 `(维度, 群系, 主体)` 查，命中不到就沿
#   `SCOPE_ORDER` 降级。
# - `FACT_TYPES`：命名事实。按 `(stat_type, subject, condition)` 精确连接，
#   没有回退语义——一个结构的箱子构成不会因为“群系层没有”而降级到维度层。
SPATIAL_TYPES = (
    "ore_exposure",
    "ore_density",
    "block_density",
    "block_exposure",
    "section_fill",
    "biome_patch",
    "structure_density",
    "mob_density",
    "spawn_distribution",
)

FACT_TYPES = (
    "loot_expectation",
    "structure_content",
    "trade_offer",
    "mob_spawn",
)

assert set(SPATIAL_TYPES) | set(FACT_TYPES) == set(STAT_TYPES), "新增 stat_type 必须归空间测量或命名事实"


class StatError(ValueError):
    """统计行不合法。"""


@dataclass(frozen=True)
class WorldStat:
    """一条世界统计。

    `parent_scope` 指向回退链上的下一层主键，用于数据一致性检查；
    解析时按 `SCOPE_ORDER` 推导，不依赖它。
    """

    pack_version: str
    scope_level: str
    dimension: str
    biome: str
    stat_type: str
    subject: str
    condition: str
    value: dict
    sample_size: int
    confidence: str
    parent_scope: tuple[str, ...] | None = None
    derived_from: tuple[str, ...] = ()
    provenance: str = ""
    synthetic: bool = False
    note: str = ""

    @property
    def key(self) -> tuple[str, ...]:
        return (
            self.pack_version,
            self.scope_level,
            self.dimension,
            self.biome,
            self.stat_type,
            self.subject,
            self.condition,
        )

    @property
    def stat_key(self) -> tuple[str, ...]:
        """不含 `pack_version` 的键，用于跨版本比较同一统计。"""
        return self.key[1:]

    def as_dict(self) -> dict:
        """序列化时省略空默认值；`note`/`derived_from`/`provenance` 由 store 单独折叠。"""
        out: dict = {
            "pack_version": self.pack_version,
            "scope_level": self.scope_level,
            "dimension": self.dimension,
            "biome": self.biome,
            "stat_type": self.stat_type,
            "subject": self.subject,
            "condition": self.condition,
            "value": self.value,
            "sample_size": self.sample_size,
            "confidence": self.confidence,
        }
        if self.parent_scope:
            out["parent_scope"] = list(self.parent_scope)
        if self.derived_from:
            out["derived_from"] = list(self.derived_from)
        if self.provenance:
            out["provenance"] = self.provenance
        if self.synthetic:
            out["synthetic"] = True
        if self.note:
            out["note"] = self.note
        return out

    @classmethod
    def from_dict(cls, raw: dict) -> WorldStat:
        if not isinstance(raw, dict):
            raise StatError(f"统计行必须是对象，实际是 {type(raw).__name__}")

        allowed = set(cls.__dataclass_fields__)
        unknown = set(raw) - allowed
        if unknown:
            raise StatError(f"统计行含未知字段：{sorted(unknown)}")

        missing = {"pack_version", "scope_level", "stat_type", "value", "sample_size", "confidence"} - set(raw)
        if missing:
            raise StatError(f"统计行缺字段：{sorted(missing)}")

        for name in ("pack_version", "scope_level", "dimension", "biome", "stat_type", "subject", "condition"):
            if not isinstance(raw.get(name, ""), str):
                raise StatError(f"字段 {name} 必须是字符串：{raw.get(name)!r}")

        scope = raw["scope_level"]
        if scope not in SCOPE_LEVELS:
            raise StatError(f"scope_level {scope!r} 不在 {list(SCOPE_LEVELS)} 内")

        stat_type = raw["stat_type"]
        if stat_type not in STAT_VALUE_SCHEMA:
            raise StatError(f"stat_type {stat_type!r} 不在 {list(STAT_TYPES)} 内")

        confidence = raw["confidence"]
        if confidence not in CONFIDENCE_LEVELS:
            raise StatError(f"confidence {confidence!r} 不在 {list(CONFIDENCE_LEVELS)} 内")

        sample_size = raw["sample_size"]
        if not isinstance(sample_size, int) or isinstance(sample_size, bool) or sample_size < 0:
            raise StatError(f"sample_size 必须是非负整数：{sample_size!r}")

        stat = cls(
            pack_version=raw["pack_version"],
            scope_level=scope,
            dimension=raw.get("dimension", ""),
            biome=raw.get("biome", ""),
            stat_type=stat_type,
            subject=raw.get("subject", ""),
            condition=raw.get("condition", ""),
            value=raw["value"],
            sample_size=sample_size,
            confidence=confidence,
            parent_scope=tuple(raw["parent_scope"]) if raw.get("parent_scope") else None,
            derived_from=tuple(raw.get("derived_from") or ()),
            provenance=raw.get("provenance", "") or "",
            synthetic=bool(raw.get("synthetic", False)),
            note=raw.get("note", ""),
        )
        stat.validate()
        return stat

    def validate(self) -> None:
        """校验分层语义与 `value` 形状。构造即校验，避免坏行进入下游。"""
        if self.scope_level == "global":
            if self.dimension or self.biome:
                raise StatError(f"{self.key}: global 行不得带 dimension/biome")
        elif self.scope_level == "dimension":
            if not self.dimension or self.biome:
                raise StatError(f"{self.key}: dimension 行必须带 dimension、不得带 biome")
        elif self.scope_level == "biome":
            if not self.dimension or not self.biome:
                raise StatError(f"{self.key}: biome 行必须同时带 dimension 与 biome")
        elif self.scope_level == "biome_subject":
            if not self.dimension or not self.biome or not self.subject:
                raise StatError(f"{self.key}: biome_subject 行必须同时带 dimension、biome 与 subject")

        if not isinstance(self.value, dict):
            raise StatError(f"{self.key}: value 必须是对象")

        schema = STAT_VALUE_SCHEMA[self.stat_type]
        required = set(schema["required"])
        optional = set(schema["optional"])
        present = set(self.value)
        missing = required - present
        unknown = present - required - optional
        if missing:
            raise StatError(f"{self.key}: value 缺键 {sorted(missing)}")
        if unknown:
            raise StatError(f"{self.key}: value 含未知键 {sorted(unknown)}")

        if self.parent_scope is not None and len(self.parent_scope) != 7:
            raise StatError(f"{self.key}: parent_scope 必须是七元主键")


@dataclass
class WorldStatStore:
    """按主键索引的统计集合。

    `revision` 每次改动自增，解析器的缓存以它为版本号——不需要手工清缓存。

    另维护两级只读索引（`stat_type` 与 `(stat_type, subject)`）：消费端按
    表名/方块名查事实时用它们，避免为了 1 行扫全表。索引只由
    `add` / `replace` / `remove` 维护，不要直接改 `rows`。
    """

    rows: dict[tuple[str, ...], WorldStat] = field(default_factory=dict)
    revision: int = 0
    _by_type: dict[str, list[WorldStat]] = field(
        default_factory=dict, repr=False, compare=False
    )
    _by_type_subject: dict[tuple[str, str], list[WorldStat]] = field(
        default_factory=dict, repr=False, compare=False
    )

    def of(self, stat_type: str, subject: str) -> list[WorldStat]:
        """某类统计里某个 `subject` 的全部行（通常 1–2 行）。"""
        return self._by_type_subject.get((stat_type, subject), [])

    def of_type(self, stat_type: str) -> list[WorldStat]:
        """某类统计的全部行。"""
        return self._by_type.get(stat_type, [])

    def _index_add(self, stat: WorldStat) -> None:
        self._by_type.setdefault(stat.stat_type, []).append(stat)
        self._by_type_subject.setdefault((stat.stat_type, stat.subject), []).append(stat)

    def _index_remove(self, stat: WorldStat) -> None:
        bucket = self._by_type.get(stat.stat_type)
        if bucket is not None:
            bucket.remove(stat)
        bucket = self._by_type_subject.get((stat.stat_type, stat.subject))
        if bucket is not None:
            bucket.remove(stat)

    def add(self, stat: WorldStat) -> None:
        if stat.key in self.rows:
            raise StatError(f"主键重复：{stat.key}")
        self.rows[stat.key] = stat
        self._index_add(stat)
        self.revision += 1

    def replace(self, stat: WorldStat) -> None:
        """覆盖或新增一条。用于调参与测试。"""
        previous = self.rows.get(stat.key)
        if previous is not None:
            self._index_remove(previous)
        self.rows[stat.key] = stat
        self._index_add(stat)
        self.revision += 1

    def remove(self, key: tuple[str, ...]) -> WorldStat:
        try:
            stat = self.rows.pop(key)
        except KeyError:
            raise StatError(f"主键不存在：{key}") from None
        self._index_remove(stat)
        self.revision += 1
        return stat

    def pack_versions(self) -> set[str]:
        return {stat.pack_version for stat in self.rows.values()}

    def of_pack(self, pack_version: str) -> list[WorldStat]:
        return [stat for stat in self.rows.values() if stat.pack_version == pack_version]

    def check_parents(self) -> list[str]:
        """返回 `parent_scope` 指向不存在行的主键描述。"""
        problems: list[str] = []
        for stat in self.rows.values():
            if stat.parent_scope is None:
                continue
            if stat.parent_scope not in self.rows:
                problems.append(f"{stat.key} → {stat.parent_scope}")
        return problems
