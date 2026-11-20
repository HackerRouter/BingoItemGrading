"""编排：读 `target.json`、遍历分析器、出缺口清单。"""

from __future__ import annotations

import json

from pathlib import Path
from .. import ore_stats
from .biomes import _import_biome_patches, _import_biomes
from .exposure import _import_cave_exposure
from .model import BIOME_FILE, BIOME_PATCH_FILE, CAVE_EXPOSURE_FILE, ENTITY_FILE, HISTOGRAM_FILE, ImportError_, ImportResult, LAVA_FILE, LOOT_STAT_TYPE, ORE_STATS_INDEX, STRUCTURE_FILE, SUPPORTED_SCHEMA, Target, UNMAPPED_ANALYZERS, _all_dimensions, _read, _results_of
from .ores import _import_ore_stats
from .structures import _import_structures
from .world import _import_block_histogram, _import_entities, _import_lava




def read_target(run_dir: Path) -> Target:
    """从 `summary.json` 读溯源信息。缺 target 视为 v1 产物。"""
    summary = Path(run_dir) / "summary.json"
    if not summary.exists():
        raise ImportError_(f"{run_dir} 缺 summary.json")
    doc = json.loads(summary.read_text(encoding="utf-8"))
    if doc.get("schemaVersion") != SUPPORTED_SCHEMA:
        raise ImportError_(
            f"{summary} 的 schemaVersion={doc.get('schemaVersion')!r}，只认 {SUPPORTED_SCHEMA}"
        )
    raw = doc.get("target") or {}
    return Target(
        minecraftVersion=raw.get("minecraftVersion", ""),
        levelName=raw.get("levelName", ""),
        seed=raw.get("seed", ""),
        seedMode=raw.get("seedMode", ""),
        serverJarSha256=raw.get("serverJarSha256", ""),
        dataPacks=list(raw.get("dataPacks") or []),
        range=dict(doc.get("range") or {}),
        generatedAt=doc.get("generatedAt", ""),
        run=Path(run_dir).name,
    )




def import_run(
    run_dir: Path,
    pack_version: str,
    *,
    dimensions: list[str] | None = None,
) -> ImportResult:
    """导入一次统计运行。`dimensions=None` 时导入产物里出现的全部维度。"""
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise ImportError_(f"统计目录不存在：{run_dir}")

    result = ImportResult(
        run=run_dir.name,
        pack_version=pack_version,
        target=read_target(run_dir),
    )
    result.gaps = {"unmeasured_stat_types": [], "unmapped_provenance": []}

    present: dict[str, str] = {}
    try:
        ore_payloads = ore_stats.dimension_payloads(run_dir)
    except ValueError as exc:
        raise ImportError_(str(exc)) from exc
    biome = _read(run_dir, BIOME_FILE)
    biome_patch = _read(run_dir, BIOME_PATCH_FILE)
    structure = _read(run_dir, STRUCTURE_FILE)
    entity = _read(run_dir, ENTITY_FILE)
    lava = _read(run_dir, LAVA_FILE)
    histogram = _read(run_dir, HISTOGRAM_FILE)
    cave_exposure = _read(run_dir, CAVE_EXPOSURE_FILE)

    targets = dimensions
    if targets is None:
        targets = _all_dimensions([ore_payloads, *_results_of(
            biome, biome_patch, structure, entity, lava, histogram, cave_exposure
        )])
    if not targets:
        raise ImportError_(f"{run_dir} 的产物里没有任何维度")

    if ore_payloads:
        present["ore-stats"] = ORE_STATS_INDEX
    if biome is not None:
        present["biome-histogram"] = BIOME_FILE
    if biome_patch is not None:
        present["biome-patch"] = BIOME_PATCH_FILE
    if structure is not None:
        present["structure-spacing"] = STRUCTURE_FILE
    if entity is not None:
        present["entity-census"] = ENTITY_FILE
    if lava is not None:
        present["lava-lakes"] = LAVA_FILE
    if histogram is not None:
        present["section-block-histogram"] = HISTOGRAM_FILE
    if cave_exposure is not None:
        present["cave-exposure"] = CAVE_EXPOSURE_FILE

    if not present:
        raise ImportError_(f"{run_dir} 里没有任何已知分析器产物：{ORE_STATS_INDEX} / {BIOME_FILE} / …")

    for dimension in targets:
        if ore_payloads:
            _import_ore_stats(ore_payloads, result, pack_version, dimension, run_dir)
        for doc, importer in (
            (biome, _import_biomes),
            (biome_patch, _import_biome_patches),
            (structure, _import_structures),
            (entity, _import_entities),
            (lava, _import_lava),
            (histogram, _import_block_histogram),
            (cave_exposure, _import_cave_exposure),
        ):
            if doc is None:
                continue
            if dimension not in (doc.get("result") or {}):
                continue
            importer(doc, result, pack_version, dimension, run_dir)

    for name, reason in UNMAPPED_ANALYZERS.items():
        if (run_dir / f"{name}.json").exists():
            result.unmapped_analyzers[name] = reason

    result.gaps["unmeasured_stat_types"] = _missing_stat_types(result)
    result.dimensions = list(targets)
    return result




def _missing_stat_types(result: ImportResult) -> list[str]:
    """采集侧负责但没产出的统计类型。

    下面两类不由 `worldgen.import_run` 产出，列进「采集侧缺测」会误导补数据的先后顺序：

    - `loot_expectation`：本项目 `bg data loot` 从战利品表算；
    - `structure_content` / `trade_offer`：分别由 `importers/structure.py`、
      `importers/trade.py` 从结构内部产物与交易事实导入。
    """
    from ...model import STAT_TYPES

    elsewhere = {LOOT_STAT_TYPE, "structure_content", "trade_offer", "mob_spawn"}
    own = [name for name in STAT_TYPES if name not in elsewhere]
    return [name for name in own if name not in result.imported]
