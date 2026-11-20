"""统计导入器：v2 产物 → world_stat 行。

用临时目录里的最小产物，不依赖 `ref/` 下的真实运行结果。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bingo_grading.stats.importers import worldgen

PACK = "26.3"
DIM = "minecraft:overworld"

TARGET = {
    "minecraftVersion": "26.3",
    "levelName": "world",
    "loader": "fabric",
    "seed": "439625976969540166",
    "seedMode": "random",
    "serverJarSha256": "a3" * 32,
    "dataPacks": [
        {"id": "FASBingoWorldgen_26.1_2.1.0-lava-lakes", "source": "world", "enabled": True, "sha256": "f4" * 32}
    ],
}

RANGE = {
    "shape": "square",
    "center": [0, 0],
    "radius": 1100,
    "boundChunks": {"x": [-69, 69], "z": [-69, 69]},
    "chunksScanned": 19044,
    "chunksSkipped": 6877,
    "skippedReason": "world 内含超出该统计范围的区块，已跳过",
}

UNITS = {"distance": "block", "density": "per_chunk", "area": "block^2"}


def write(
    run: Path,
    name: str,
    result: dict,
    *,
    schema: int = 2,
    ok: bool = True,
    extra: dict | None = None,
) -> None:
    doc = {
        "analyzer": name.removesuffix(".json"),
        "schemaVersion": schema,
        "generatedAt": "2026-01-01T00:00:00.000Z",
        "target": TARGET,
        "range": RANGE,
        "units": UNITS,
        "config": {},
        "ok": ok,
        "errors": [],
        "result": result,
    }
    if extra:
        doc.update(extra)
    (run / name).write_text(json.dumps(doc), encoding="utf-8")


def write_summary(run: Path, *, schema: int = 2) -> None:
    doc = {
        "schemaVersion": schema,
        "generatedAt": "2026-01-01T00:00:01.000Z",
        "target": TARGET,
        "world": "D:\\x\\.server\\26.3\\world",
        "dimensions": [DIM],
        "range": RANGE,
        "analyzers": [],
    }
    (run / "summary.json").write_text(json.dumps(doc), encoding="utf-8")


def ore_cell(total: float, air: float, water: float, buried: float, air_pct: float) -> dict:
    return {
        "avgTotal": total,
        "avgAirExposed": air,
        "avgWaterExposed": water,
        "avgBoth": 0.0,
        "avgBuried": buried,
        "avgUnknownEdge": 0.0,
        "airPct": air_pct,
        "waterPct": 5.0,
    }


@pytest.fixture()
def run(tmp_path: Path) -> Path:
    path = tmp_path / "2026-01-01T00-00-00-000Z"
    path.mkdir()
    write_summary(path)

    write(
        path,
        "ore-stats.json",
        {},
        extra={"resultFiles": {DIM: "ore-stats.overworld.json"}},
    )
    write(
        path,
        "ore-stats.overworld.json",
        {
            DIM: {
                "chunks": 4000,
                "totalColumns": 1_024_000,
                "minChunks": 200,
                "minOreSamples": 100,
                "top": 10,
                "reliableBiomes": 2,
                "exposureBlockList": ["minecraft:redstone_ore"],
                "bulkBlockList": ["minecraft:chorus_plant"],
                "biomes": [
                    {
                        "id": "minecraft:badlands",
                        "columns": 4656,
                        "chunkEquivalent": 18.19,
                        "chunks": 38,
                        "reliable": False,
                        "exposureBlocks": 483,
                        "bulkBlocks": 0,
                        "exposure": {
                            "minecraft:redstone_ore": {
                                "count": 483,
                                "avgPerChunk": 26.5567,
                                "airExposed": 10,
                                "avgAirExposed": 0.55,
                                "waterExposed": 0,
                                "avgWaterExposed": 0.0,
                                "both": 0,
                                "buried": 473,
                                "avgBuried": 26.0,
                                "unknownEdge": 0,
                                "airPct": 2.07,
                                "waterPct": 0.0,
                                "reliableExposure": True,
                            }
                        },
                        "bulk": {},
                        "sections": [
                            {
                                "yRange": [0, 15],
                                "blocks": 400,
                                "exposure": {
                                    "minecraft:redstone_ore": {
                                        "count": 483,
                                        "avgPerChunk": 26.5567,
                                        "share": 1.0,
                                        "airPct": 2.07,
                                    }
                                },
                                "bulk": {},
                            }
                        ],
                    },
                    {
                        "id": "minecraft:plains",
                        "columns": 407142,
                        "chunkEquivalent": 1590.4,
                        "chunks": 3283,
                        "reliable": True,
                        "exposureBlocks": 5901,
                        "bulkBlocks": 12,
                        "exposure": {
                            "minecraft:redstone_ore": {
                                "count": 5901,
                                "avgPerChunk": 3.7104,
                                "airExposed": 0,
                                "avgAirExposed": 0.0,
                                "waterExposed": 0,
                                "avgWaterExposed": 0.0,
                                "both": 0,
                                "buried": 5901,
                                "avgBuried": 3.7104,
                                "unknownEdge": 0,
                                "airPct": 0.0,
                                "waterPct": 0.0,
                                "reliableExposure": True,
                            }
                        },
                        "bulk": {
                            "minecraft:chorus_plant": {"count": 12, "avgPerChunk": 0.0075}
                        },
                        "sections": [
                            {
                                "yRange": [0, 15],
                                "blocks": 5901,
                                "exposure": {
                                    "minecraft:redstone_ore": {
                                        "count": 5901,
                                        "avgPerChunk": 3.7104,
                                        "share": 1.0,
                                        "airPct": 0.0,
                                    }
                                },
                                "bulk": {},
                            }
                        ],
                    },
                ],
                "sectionProfiles": {},
                "note": "测试夹具",
            }
        },
    )

    write(
        path,
        "biome-histogram.json",
        {
            DIM: {
                "chunks": 4000,
                "columns": 64000,
                "surface": {
                    "uniqueBiomes": 2,
                    "biomes": [
                        {"id": "minecraft:plains", "cells": 48000, "share": 75.0},
                        {"id": "minecraft:forest", "cells": 16000, "share": 25.0},
                    ],
                },
                "underground": {
                    "columns": 64000,
                    "differing": 100,
                    "sameAsSurface": {"columns": 60000, "share": 93.75},
                    "uniqueBiomes": 1,
                    "biomes": [{"id": "minecraft:lush_caves", "cells": 4000, "share": 6.25}],
                },
            }
        },
    )

    write(
        path,
        "biome-patch.json",
        {
            DIM: {
                "columns": 64000,
                "boundaryColumns": 0,
                "top": 5,
                "biomes": [
                    {
                        "id": "minecraft:badlands",
                        "columns": 4656,
                        "areaFraction": 0.000955,
                        "patches": {
                            "count": 12,
                            "meanAreaBlocks": 388.0,
                            "medianAreaBlocks": 128.0,
                            "areaVariance": 1.2692,
                            "maxAreaBlocks": 1280.0,
                            "edgeTouchCount": 0,
                        },
                        "openSurfaceShare": 0.9354,
                        "neighbors": {"minecraft:desert": 0.1367},
                    }
                ],
            }
        },
    )

    write(
        path,
        "structure-spacing.json",
        {
            DIM: {
                "chunks": 4000,
                "structureStarts": 30,
                "groups": [
                    {
                        "set": "minecraft:villages",
                        "dimension": DIM,
                        "count": 20,
                        "setKnown": True,
                        "structureIds": ["minecraft:village_plains"],
                        "meanNNBlocks": 288.3,
                        "meanNNChunks": 18.02,
                        "medianNNBlocks": 260.0,
                        "trimmed": None,
                        "configured": {"spacingChunks": 34, "separationChunks": 8},
                    },
                    {
                        "set": "minecraft:strongholds",
                        "dimension": DIM,
                        "count": 6,
                        "setKnown": True,
                        "structureIds": ["minecraft:stronghold"],
                        "meanNNBlocks": 626.1,
                        "meanNNChunks": 39.13,
                        "medianNNBlocks": 600.0,
                        "trimmed": None,
                        "configured": {"spacingChunks": None, "separationChunks": None},
                    },
                    {
                        "set": "minecraft:woodland_mansions",
                        "dimension": DIM,
                        "count": 1,
                        "setKnown": True,
                        "structureIds": ["minecraft:mansion"],
                        "meanNNBlocks": None,
                        "meanNNChunks": None,
                        "medianNNBlocks": None,
                        "trimmed": None,
                        "configured": {"spacingChunks": 80, "separationChunks": 20},
                    },
                ],
            }
        },
    )

    write(
        path,
        "entity-census.json",
        {
            DIM: {
                "chunks": 4000,
                "entities": 100,
                "byType": {
                    "minecraft:pig": {
                        "category": "land",
                        "count": 270,
                        "perChunk": 0.0675,
                        "chunksPer": 14.81,
                        "avgY": 69.2,
                        "group": {"groups": 112, "perChunk": 0.028, "chunksPer": 35.7, "avgSize": 2.41},
                    },
                    "minecraft:blaze": {
                        "category": "monster",
                        "count": 0,
                        "perChunk": 0,
                        "chunksPer": None,
                        "avgY": None,
                        "group": {"groups": 0, "perChunk": 0, "chunksPer": None, "avgSize": 0},
                    },
                },
            }
        },
    )

    write(
        path,
        "lava-lakes.json",
        {
            DIM: {
                "chunks": 4000,
                "lavaBlocks": 100,
                "surface": {
                    "lakes": 33,
                    "groups": {"count": 24, "mergedPairs": 0, "avgSize": 60},
                    "lakeBlocks": 1980,
                    "spacing": {
                        "count": 24,
                        "meanNNBlocks": 240.6,
                        "meanNNChunks": 15.04,
                        "medianNNBlocks": 215.9,
                        "minNNBlocks": 85.8,
                        "maxNNBlocks": 607.5,
                    },
                    "density": {"lakesPer1000LandChunks": 3.42, "groupsPer1000LandChunks": 2.49},
                },
                "underground": {"yRange": [-62, 59], "lavaBlocks": 878274},
            }
        },
    )
    # 真实运行必然带逐区段直方图；它同时产出 block_density 与 section_fill
    write(
        path,
        "section-block-histogram.json",
        {
            DIM: {
                "chunks": 4000,
                "includeAir": False,
                "sections": [
                    {
                        "y": 0,
                        "yRange": [0, 15],
                        "chunks": 4000,
                        "avgTotal": 4000.0,
                        "blocks": [
                            {"id": "minecraft:stone", "avg": 3900.0, "share": 97.5},
                            {"id": "minecraft:clay", "avg": 100.0, "share": 2.5},
                        ],
                    }
                ],
            }
        },
    )
    # 6 面暴露（天空/洞穴/水/埋着四分）
    write(
        path,
        "cave-exposure.json",
        {
            DIM: {
                "chunks": 4000,
                "minSamples": 200,
                "blocks": [
                    {
                        "id": "minecraft:clay",
                        "count": 400000,
                        "avgPerChunk": 100.0,
                        "skyAirExposed": 561,
                        "skyAirPct": 0.14,
                        "caveAirExposed": 12600,
                        "caveAirPct": 3.15,
                        "bothAir": 22,
                        "bothAirPct": 0.01,
                        "airExposed": 13183,
                        "airPct": 3.29,
                        "caveShareOfAirPct": 95.7,
                        "waterExposed": 5000,
                        "waterPct": 1.25,
                        "buried": 381817,
                        "buriedPct": 95.45,
                        "unknownEdge": 0,
                        "unknownPct": 0.0,
                        "reliable": True,
                    }
                ],
            }
        },
    )
    return path


def rows_of(result, stat_type: str) -> list:
    return [row for row in result.rows if row.stat_type == stat_type]


def test_imports_all_measured_types(run: Path) -> None:
    result = worldgen.import_run(run, PACK)
    types = {row.stat_type for row in result.rows}
    assert types == {
        "ore_exposure",
        "ore_density",
        "block_density",
        "block_exposure",
        "section_fill",
        "structure_density",
        "spawn_distribution",
        "mob_density",
        "biome_patch",
    }


def test_target_is_captured(run: Path) -> None:
    result = worldgen.import_run(run, PACK)
    assert result.target.minecraftVersion == "26.3"
    assert result.target.seed == "439625976969540166"
    assert result.target.seedMode == "random"
    assert result.target.pack_fingerprint() == "f4" * 32
    assert result.summary()["target"]["dataPacks"] == [
        "FASBingoWorldgen_26.1_2.1.0-lava-lakes"
    ]


def test_ore_exposure_is_biome_level(run: Path) -> None:
    """暴露从维度级改为群系级：上游 ore-stats 只给群系粒度。"""
    result = worldgen.import_run(run, PACK)
    rows = {row.biome: row for row in rows_of(result, "ore_exposure")}
    badlands = rows["minecraft:badlands"]
    assert badlands.subject == "minecraft:redstone_ore"
    assert badlands.scope_level == "biome"
    assert badlands.value["per_chunk_density"] == 26.5567
    assert badlands.value["air_exposed_share"] == pytest.approx(0.0207)


def test_zero_count_exposure_is_not_written(run: Path) -> None:
    """群系里该方块计数为 0 时不写暴露行。"""
    result = worldgen.import_run(run, PACK)
    for row in rows_of(result, "ore_exposure"):
        assert row.value["per_chunk_density"] > 0


def test_ore_density_is_biome_level_without_exposure(run: Path) -> None:
    result = worldgen.import_run(run, PACK)
    rows = {(row.biome, row.subject): row for row in rows_of(result, "ore_density")}
    badlands = rows[("minecraft:badlands", "minecraft:redstone_ore")]
    assert badlands.scope_level == "biome"
    assert badlands.value["per_chunk_density"] == 26.5567
    assert badlands.value["equivalent_chunks"] == 18.19
    assert badlands.confidence == "low"
    assert badlands.value["reliable"] is False
    # 群系级只讲分布：不得出现暴露分量。
    assert not {"air_exposed", "buried", "air_exposed_share"} & set(badlands.value)
    # 纵段分解要带上，供「挖多深」换算。
    assert badlands.value["by_section"]["0"]["per_chunk"] == 26.5567


def test_block_density_from_bulk(run: Path) -> None:
    """非矿石方块走 bulk 类，落成 block_density。"""
    result = worldgen.import_run(run, PACK)
    rows = {(row.biome, row.subject): row for row in rows_of(result, "block_density")}
    plains = rows[("minecraft:plains", "minecraft:chorus_plant")]
    assert plains.value["per_chunk_density"] == 0.0075
    assert plains.value["reliable"] is True
    assert plains.confidence != "low"


def test_biome_patch_maps_open_surface_share(run: Path) -> None:
    result = worldgen.import_run(run, PACK)
    [row] = rows_of(result, "biome_patch")
    assert row.scope_level == "biome"
    assert row.biome == "minecraft:badlands"
    assert row.value["vertical_condition_prob"] == pytest.approx(0.9354)
    assert row.value["mean_area"] == 388.0
    assert row.value["median_area"] == 128.0
    assert row.value["area_variance"] == pytest.approx(1.2692)
    assert row.value["patches"] == 12
    assert row.value["neighbors"] == {"minecraft:desert": 0.1367}


def test_biome_patch_density_is_per_equivalent_chunk(run: Path) -> None:
    result = worldgen.import_run(run, PACK)
    [row] = rows_of(result, "biome_patch")
    equivalent = 4656 / 256
    assert row.value["patch_density"] == pytest.approx(12 / equivalent, rel=1e-3)


def test_autocorr_tier_from_variance() -> None:
    assert worldgen._autocorr_tier(0.5) == "high"
    assert worldgen._autocorr_tier(1.0) == "medium"
    assert worldgen._autocorr_tier(4.0) == "low"


def test_structure_uses_measured_distance(run: Path) -> None:
    result = worldgen.import_run(run, PACK)
    rows = {row.subject: row for row in rows_of(result, "structure_density")}
    village = rows["minecraft:villages"]
    assert village.value["expected_nearest_distance"] == 288.3
    assert village.value["spacing"] == 34
    assert village.value["observations"] == 20


def test_structure_without_configured_spacing_keeps_measurement(run: Path) -> None:
    result = worldgen.import_run(run, PACK)
    rows = {row.subject: row for row in rows_of(result, "structure_density")}
    stronghold = rows["minecraft:strongholds"]
    assert stronghold.value["expected_nearest_distance"] == 626.1
    assert "spacing" not in stronghold.value


def test_structure_derives_distance_from_spacing_when_unmeasured(run: Path) -> None:
    result = worldgen.import_run(run, PACK)
    rows = {row.subject: row for row in rows_of(result, "structure_density")}
    mansion = rows["minecraft:woodland_mansions"]
    assert mansion.value["expected_nearest_distance"] == 80 * 16 / 2
    assert mansion.confidence == "low"
    assert "configured.spacingChunks" in mansion.derived_from


def test_biome_weights_normalised_to_fraction(run: Path) -> None:
    result = worldgen.import_run(run, PACK)
    [row] = rows_of(result, "spawn_distribution")
    assert row.value["biome_weights"]["minecraft:plains"] == pytest.approx(0.75)
    assert row.value["underground_biome_weights"]["minecraft:lush_caves"] == pytest.approx(0.0625)


def test_mob_density_drops_null_fields(run: Path) -> None:
    result = worldgen.import_run(run, PACK)
    rows = {row.subject: row for row in rows_of(result, "mob_density")}
    assert rows["minecraft:pig"].value["per_chunk"] == 0.0675
    assert rows["minecraft:pig"].value["avg_group_size"] == 2.41
    assert "chunks_per" not in rows["minecraft:blaze"].value
    assert "avg_y" not in rows["minecraft:blaze"].value


def test_lava_lakes_become_feature_density(run: Path) -> None:
    result = worldgen.import_run(run, PACK)
    rows = {row.subject: row for row in rows_of(result, "structure_density")}
    lake = rows[worldgen.LAVA_SUBJECT]
    assert lake.value["expected_nearest_distance"] == 240.6
    assert lake.value["spacing"] == round(15.04 * 2)
    assert lake.value["density_per_1000_chunks"] == 3.42


def test_block_histogram_becomes_block_density(run: Path) -> None:
    """逐区段直方图 → block_density，覆盖非矿石方块。"""
    write(
        run,
        "section-block-histogram.json",
        {
            DIM: {
                "chunks": 100,
                "sections": [
                    {
                        "y": 0,
                        "yRange": [0, 15],
                        "blocks": [
                            {"id": "minecraft:clay", "avg": 10.0, "share": 5.0},
                            {"id": "minecraft:stone", "avg": 990.0, "share": 95.0},
                            {"id": "minecraft:rare", "avg": 1e-5, "share": 0.0},
                        ],
                    }
                ],
            }
        },
    )
    result = worldgen.import_run(run, PACK)
    rows = [
        row
        for row in result.rows
        if row.stat_type == "block_density" and row.subject == "minecraft:clay"
    ]
    assert len(rows) == 1
    assert rows[0].value["per_chunk_density"] == 10.0
    assert rows[0].value["total_blocks"] == 1000
    assert rows[0].value["by_section"]["0"]["y_range"] == [0, 15]

    # 每区块不足阈值的方块不导入
    rare = [
        row
        for row in result.rows
        if row.stat_type == "block_density" and row.subject == "minecraft:rare"
    ]
    assert not rare
    assert any("不足" in note for note in result.gaps.get("notes", []))


def test_missing_stat_types_are_reported(run: Path) -> None:
    result = worldgen.import_run(run, PACK)
    # loot_expectation 不由采集侧产生（本项目 `bg data loot` 算），
    # 所以它不出现在采集侧的缺测清单里。
    assert result.gaps["unmeasured_stat_types"] == []


def test_missing_dimension_is_reported_not_fabricated(run: Path) -> None:
    """指定一个产物里没有的维度：不写行，并在缺口报告里点名。"""
    result = worldgen.import_run(run, PACK, dimensions=["minecraft:the_nether"])
    assert not [row for row in result.rows if row.dimension == "minecraft:the_nether"]
    assert any("the_nether" in item for item in result.gaps["unmapped_provenance"])


def test_v1_schema_is_rejected(run: Path) -> None:
    write(run, "entity-census.json", {"byType": {}}, schema=1)
    with pytest.raises(worldgen.ImportError_, match="schemaVersion"):
        worldgen.import_run(run, PACK)


def test_missing_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(worldgen.ImportError_):
        worldgen.import_run(tmp_path / "absent", PACK)


def test_failed_analyzer_raises(run: Path) -> None:
    write(run, "ore-stats.overworld.json", {DIM: {"chunks": 1, "biomes": []}}, ok=False)
    with pytest.raises(worldgen.ImportError_, match="ok=false"):
        worldgen.import_run(run, PACK)


def test_guess_version_prefers_target(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    write_summary(run)
    assert worldgen.guess_minecraft_version(run) == "26.3"


def test_guess_version_falls_back_to_world_path(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "summary.json").write_text(
        json.dumps({"world": "D:\\x\\.server\\26.3\\world"}), encoding="utf-8"
    )
    assert worldgen.guess_minecraft_version(run) == "26.3"


def test_guess_version_absent(tmp_path: Path) -> None:
    assert worldgen.guess_minecraft_version(tmp_path) is None
