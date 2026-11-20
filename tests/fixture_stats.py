"""测试专用的虚构 `world_stat` 快照构造器。

统计层与解析器的闭环需要一套结构完整、语义自洽的多层数据（global /
dimension / biome / biome_subject），而真实快照不一定同时具备这四层。
所以这套占位数据在**测试时临时生成**，不存进 `data/`——仓库里不再有一份
会被误当实测结果的假快照。

数值不是原版实测值，也不是任何地形包的实测值，不用于标定。
"""

from __future__ import annotations

from pathlib import Path

from bingo_grading.stats.model import WorldStat, WorldStatStore
from bingo_grading.stats.store import dump

PACK = "fixture-2026.11"
NOTE = "测试构造的占位数据，非实测"

OVERWORLD = "minecraft:overworld"
NETHER = "minecraft:the_nether"
UNDERGROUND = "layer=underground"


def key(
    scope: str,
    dimension: str = "",
    biome: str = "",
    stat_type: str = "",
    subject: str = "",
    condition: str = "",
) -> tuple[str, ...]:
    return (PACK, scope, dimension, biome, stat_type, subject, condition)


def row(
    scope: str,
    dimension: str,
    biome: str,
    stat_type: str,
    subject: str,
    condition: str,
    value: dict,
    sample_size: int,
    confidence: str,
    parent: tuple[str, ...] | None = None,
    derived_from: tuple[str, ...] = (),
) -> WorldStat:
    return WorldStat(
        pack_version=PACK,
        scope_level=scope,
        dimension=dimension,
        biome=biome,
        stat_type=stat_type,
        subject=subject,
        condition=condition,
        value=value,
        sample_size=sample_size,
        confidence=confidence,
        parent_scope=parent,
        derived_from=derived_from,
        synthetic=True,
        note=NOTE,
    )


def build() -> WorldStatStore:
    store = WorldStatStore()

    # ---------- global ----------
    global_ore = key("global", stat_type="ore_exposure")
    store.add(
        row(
            "global", "", "", "ore_exposure", "", "",
            {
                "air_exposed": 6.5,
                "water_exposed": 0.8,
                "buried": 38.0,
                "per_chunk_density": 45.3,
                "air_exposed_share": 0.22,
            },
            4096, "low",
        )
    )
    global_village = key("global", stat_type="structure_density", subject="minecraft:village")
    store.add(
        row(
            "global", "", "", "structure_density", "minecraft:village", "",
            {
                "spacing": 34,
                "separation": 8,
                "biome_conditions": [
                    "minecraft:plains",
                    "minecraft:desert",
                    "minecraft:savanna",
                    "minecraft:taiga",
                    "minecraft:snowy_plains",
                ],
                "expected_nearest_distance": 120.0,
            },
            2048, "low",
            derived_from=("spacing", "separation"),
        )
    )
    global_patch = key("global", stat_type="biome_patch")
    store.add(
        row(
            "global", "", "", "biome_patch", "", "",
            {
                "patch_density": 2.4,
                "mean_area": 380.0,
                "area_variance": 0.65,
                "area_fraction": 0.18,
                "autocorr_tier": "medium",
                "vertical_condition_prob": 0.35,
            },
            4096, "low",
        )
    )
    store.add(
        row(
            "global", "", "", "loot_expectation", "", "",
            {
                "per_trigger_expected": 2.4,
                "chests_per_structure": 3.0,
                "structure_frequency": 0.42,
                "trigger": "chest_open",
            },
            1024, "low",
        )
    )
    store.add(
        row(
            "global", "", "", "spawn_distribution", "", "",
            {
                "biome_weights": {
                    "minecraft:plains": 0.18,
                    "minecraft:forest": 0.14,
                    "minecraft:desert": 0.10,
                    "minecraft:ocean": 0.25,
                    "minecraft:badlands": 0.04,
                    "minecraft:windswept_hills": 0.03,
                    "minecraft:other": 0.26,
                }
            },
            8192, "low",
        )
    )

    # ---------- dimension：主世界 ----------
    dim_village = key("dimension", OVERWORLD, stat_type="structure_density", subject="minecraft:village")
    store.add(
        row(
            "dimension", OVERWORLD, "", "structure_density", "minecraft:village", "",
            {
                "spacing": 36,
                "separation": 6,
                "biome_conditions": ["minecraft:plains", "minecraft:desert", "minecraft:savanna"],
                "expected_nearest_distance": 110.0,
            },
            1536, "medium",
            parent=global_village,
            derived_from=("spacing", "separation"),
        )
    )
    store.add(
        row(
            "dimension", OVERWORLD, "", "spawn_distribution", "", "",
            {
                "biome_weights": {
                    "minecraft:plains": 0.19,
                    "minecraft:forest": 0.15,
                    "minecraft:desert": 0.10,
                    "minecraft:ocean": 0.26,
                    "minecraft:badlands": 0.04,
                    "minecraft:windswept_hills": 0.03,
                    "minecraft:other": 0.23,
                }
            },
            4096, "medium",
        )
    )

    # ---------- dimension：主世界地下 ----------
    dim_redstone = key("dimension", OVERWORLD, stat_type="ore_exposure", subject="minecraft:redstone_ore", condition=UNDERGROUND)
    store.add(
        row(
            "dimension", OVERWORLD, "", "ore_exposure", "minecraft:redstone_ore", UNDERGROUND,
            {
                "air_exposed": 2.1,
                "water_exposed": 0.3,
                "buried": 88.0,
                "per_chunk_density": 90.4,
                "air_exposed_share": 0.12,
            },
            2048, "medium",
            parent=global_ore,
        )
    )
    store.add(
        row(
            "dimension", OVERWORLD, "", "ore_exposure", "minecraft:diamond_ore", UNDERGROUND,
            {
                "air_exposed": 0.4,
                "water_exposed": 0.1,
                "buried": 34.0,
                "per_chunk_density": 34.5,
                "air_exposed_share": 0.03,
            },
            2048, "medium",
            parent=global_ore,
        )
    )

    # ---------- dimension：下界 ----------
    store.add(
        row(
            "dimension", NETHER, "", "ore_exposure", "minecraft:ancient_debris", "",
            {
                "air_exposed": 0.9,
                "water_exposed": 0.0,
                "buried": 12.0,
                "per_chunk_density": 12.9,
                "air_exposed_share": 0.05,
            },
            1024, "medium",
            parent=global_ore,
        )
    )
    store.add(
        row(
            "dimension", NETHER, "", "biome_patch", "minecraft:nether_quartz_ore", "",
            {
                "patch_density": 6.0,
                "mean_area": 120.0,
                "area_variance": 0.90,
                "area_fraction": 0.30,
                "autocorr_tier": "high",
                "vertical_condition_prob": 0.80,
            },
            1024, "medium",
            parent=global_patch,
        )
    )

    # ---------- biome ----------
    biomes = {
        "minecraft:badlands": {
            "ore_subject": "minecraft:gold_ore",
            "ore": {
                "air_exposed": 14.0,
                "water_exposed": 0.2,
                "buried": 6.0,
                "per_chunk_density": 20.2,
                "air_exposed_share": 0.55,
            },
            "structure": (40, 10, 140.0),
            "patch": (1.1, 620.0, 0.85, 0.21, "high", 0.15),
            "loot": (1.9, 2.4, 0.03),
            "spawn": {"minecraft:badlands": 0.70, "minecraft:desert": 0.20, "minecraft:other": 0.10},
            "samples": (192, 384, 256, 128, 512),
            "confidence": "medium",
        },
        "minecraft:windswept_hills": {
            "ore_subject": "minecraft:emerald_ore",
            "ore": {
                "air_exposed": 1.2,
                "water_exposed": 0.0,
                "buried": 5.5,
                "per_chunk_density": 6.7,
                "air_exposed_share": 0.08,
            },
            "structure": (55, 12, 210.0),
            "patch": (0.35, 240.0, 1.15, 0.05, "low", 0.90),
            "loot": (1.5, 2.0, 0.01),
            "spawn": {"minecraft:windswept_hills": 0.55, "minecraft:taiga": 0.25, "minecraft:other": 0.20},
            "samples": (128, 192, 128, 64, 256),
            "confidence": "low",
        },
        "minecraft:plains": {
            "ore_subject": "minecraft:iron_ore",
            "ore": {
                "air_exposed": 3.4,
                "water_exposed": 0.5,
                "buried": 22.0,
                "per_chunk_density": 25.9,
                "air_exposed_share": 0.20,
            },
            "structure": (28, 6, 90.0),
            "patch": (4.2, 900.0, 0.30, 0.42, "high", 0.05),
            "loot": (2.6, 3.6, 0.08),
            "spawn": {"minecraft:plains": 0.68, "minecraft:forest": 0.22, "minecraft:other": 0.10},
            "samples": (256, 512, 384, 192, 768),
            "confidence": "medium",
        },
    }

    for biome, data in biomes.items():
        samples = data["samples"]
        confidence = data["confidence"]
        subject = data["ore_subject"]

        store.add(
            row(
                "biome", OVERWORLD, biome, "ore_exposure", subject, "",
                data["ore"], samples[0], confidence, parent=global_ore,
            )
        )
        spacing, separation, expected = data["structure"]
        store.add(
            row(
                "biome", OVERWORLD, biome, "structure_density", "minecraft:village", "",
                {
                    "spacing": spacing,
                    "separation": separation,
                    "biome_conditions": [biome],
                    "expected_nearest_distance": expected,
                },
                samples[1], confidence,
                parent=dim_village,
                derived_from=("spacing", "separation"),
            )
        )
        density, area, variance, fraction, autocorr, vertical = data["patch"]
        store.add(
            row(
                "biome", OVERWORLD, biome, "biome_patch", "", "",
                {
                    "patch_density": density,
                    "mean_area": area,
                    "area_variance": variance,
                    "area_fraction": fraction,
                    "autocorr_tier": autocorr,
                    "vertical_condition_prob": vertical,
                },
                samples[2], confidence, parent=global_patch,
            )
        )
        per_chest, chests, frequency = data["loot"]
        store.add(
            row(
                "biome", OVERWORLD, biome, "loot_expectation", "minecraft:village", "",
                {
                    "per_trigger_expected": per_chest,
                    "chests_per_structure": chests,
                    "structure_frequency": frequency,
                    "trigger": "chest_open",
                },
                samples[3], confidence, parent=dim_village,
            )
        )
        store.add(
            row(
                "biome", OVERWORLD, biome, "spawn_distribution", "", "",
                {"biome_weights": data["spawn"]},
                samples[4], confidence,
            )
        )

    # ---------- biome_subject：细层样例 ----------
    store.add(
        row(
            "biome_subject", OVERWORLD, "minecraft:badlands", "ore_exposure", "minecraft:gold_ore", "",
            {
                "air_exposed": 18.5,
                "water_exposed": 0.1,
                "buried": 4.0,
                "per_chunk_density": 22.6,
                "air_exposed_share": 0.68,
            },
            96, "medium",
            parent=key("biome", OVERWORLD, "minecraft:badlands", "ore_exposure", "minecraft:gold_ore"),
        )
    )

    return store


def write_snapshot(directory: Path) -> Path:
    """把占位快照写到 `directory/`（meta + spatial + facts），返回目录路径。"""
    store = build()
    problems = store.check_parents()
    if problems:
        raise AssertionError(f"parent_scope 指向不存在的行：{problems}")
    dump(store, directory)
    return directory
