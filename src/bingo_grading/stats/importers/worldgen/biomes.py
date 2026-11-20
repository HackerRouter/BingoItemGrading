"""群系：权重直方图与斑块尺寸。"""

from __future__ import annotations


from pathlib import Path
from ...model import WorldStat
from .model import BIOME_FILE, BIOME_PATCH_FILE, ImportResult, _provenance, _require_dimension, _round, confidence_for




def _import_biomes(
    doc: dict, result: ImportResult, pack: str, dimension: str, run_dir: Path
) -> None:
    payload = _require_dimension(doc, dimension, BIOME_FILE)
    chunks = int(payload.get("chunks") or 0)
    surface = payload.get("surface") or {}
    underground = payload.get("underground") or {}
    provenance = _provenance(run_dir, BIOME_FILE)

    weights = {item["id"]: _round(item["share"] / 100.0) for item in surface.get("biomes", [])}
    if not weights:
        return

    value: dict = {"biome_weights": weights}
    underground_weights = {
        item["id"]: _round(item["share"] / 100.0) for item in underground.get("biomes", [])
    }
    if underground_weights:
        value["underground_biome_weights"] = underground_weights

    result.rows.append(
        WorldStat(
            pack_version=pack,
            scope_level="dimension",
            dimension=dimension,
            biome="",
            stat_type="spawn_distribution",
            subject="",
            condition="",
            value=value,
            sample_size=chunks,
            confidence=confidence_for(chunks),
            derived_from=("surface.biomes.share",),
            provenance=provenance,
            note="权重为地表面积占比，用作出生点分布代理；不是出生点实测分布",
        )
    )
    result.imported["spawn_distribution"] = 1




def _import_biome_patches(
    doc: dict, result: ImportResult, pack: str, dimension: str, run_dir: Path
) -> None:
    """群系斑块规模：连成多大一片、地表开不开放、邻接哪些群系。"""
    payload = _require_dimension(doc, dimension, BIOME_PATCH_FILE)
    provenance = _provenance(run_dir, BIOME_PATCH_FILE)

    for biome in payload.get("biomes") or []:
        biome_id = biome.get("id")
        patches = biome.get("patches") or {}
        if not isinstance(biome_id, str) or not patches.get("count"):
            result.gaps["unmapped_provenance"].append(f"斑块条目不可用：{biome.get('id')}")
            continue

        columns = int(biome.get("columns") or 0)
        equivalent = columns / 256 if columns else 0.0
        value: dict = {
            # 每等效区块的斑块数。用「等效区块」而不是列数，避免与其它密度量纲混淆。
            "patch_density": _round(patches["count"] / equivalent, 6) if equivalent else 0.0,
            "mean_area": _round(patches.get("meanAreaBlocks", 0)),
            "area_variance": _round(patches.get("areaVariance", 0)),
            "area_fraction": _round(biome.get("areaFraction", 0), 6),
            # 地表开放性：该群系真正可走过去的地表比例。
            "vertical_condition_prob": _round(biome.get("openSurfaceShare", 0)),
        }
        if patches.get("medianAreaBlocks") is not None:
            value["median_area"] = _round(patches["medianAreaBlocks"])
        if patches.get("maxAreaBlocks") is not None:
            value["max_area"] = _round(patches["maxAreaBlocks"])
        if patches.get("edgeTouchCount") is not None:
            # 触及扫描边界的斑块会让 mean_area 系统性偏低，标出来供下游判断。
            value["edge_touch"] = int(patches["edgeTouchCount"])
        if biome.get("neighbors"):
            value["neighbors"] = {
                key: _round(share) for key, share in (biome["neighbors"] or {}).items()
            }
        value["patches"] = int(patches["count"])

        # 采集侧没有单独给自相关档位；由斑块面积变异系数推导，档位边界见文档。
        value["autocorr_tier"] = _autocorr_tier(value["area_variance"])

        result.rows.append(
            WorldStat(
                pack_version=pack,
                scope_level="biome",
                dimension=dimension,
                biome=biome_id,
                stat_type="biome_patch",
                subject="",
                condition="",
                value=value,
                sample_size=int(equivalent) or 1,
                confidence="low" if patches["count"] < 10 else "medium",
                derived_from=("patches.count", "patches.areaVariance", "openSurfaceShare"),
                provenance=provenance,
                note=(
                    "patch_density 单位为「每等效区块的斑块数」；"
                    "area_variance 是变异系数平方；edge_touch>0 表示有斑块被扫描边界截断"
                ),
            )
        )
        result.imported["biome_patch"] = result.imported.get("biome_patch", 0) + 1




def _autocorr_tier(area_variance: float) -> str:
    """由面积变异系数平方分档。斑块大小越不均，空间自相关越弱。"""
    if area_variance < 1.0:
        return "high"
    if area_variance < 4.0:
        return "medium"
    return "low"
