"""维度级方块暴露（六面邻接）。"""

from __future__ import annotations


from pathlib import Path
from ...model import WorldStat
from .model import CAVE_EXPOSURE_FILE, ImportResult, _provenance, _require_dimension, _round




def _import_cave_exposure(
    doc: dict, result: ImportResult, pack: str, dimension: str, run_dir: Path
) -> None:
    """逐方块的 6 面暴露分解 → `block_exposure`（维度级）。

    上游把「贴着什么」拆成四类，这正是采集模型要分的东西：

    - `skyAirPct`：地形高度之上的空气 → 露在地表，走过去就能拿；
    - `waterPct`：水 → 水下露头，潜下去就能拿；
    - `caveAirPct`：洞穴空气 → 要下到洞里，但不用盲挖岩层；
    - `buriedPct`：四面都不通 → 得挖穿。

    与 `ore_exposure` 的区别是它把天空与洞穴拆开了：`ore_exposure.air_exposed_share`
    把两者混在一起，判不了「地表露出」（ADR 0014）。
    """
    payload = _require_dimension(doc, dimension, CAVE_EXPOSURE_FILE)
    chunks = int(payload.get("chunks") or 0)
    min_samples = int(payload.get("minSamples") or 0)
    provenance = _provenance(run_dir, CAVE_EXPOSURE_FILE)
    for block in payload.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        block_id = block.get("id")
        count = block.get("count")
        if not isinstance(block_id, str) or not count:
            continue
        confidence = "high" if count >= min_samples else "low"
        value = {
            "per_chunk_density": _round(block.get("avgPerChunk") or 0),
            "sky_air_share": _round((block.get("skyAirPct") or 0) / 100.0),
            "cave_air_share": _round((block.get("caveAirPct") or 0) / 100.0),
            "water_share": _round((block.get("waterPct") or 0) / 100.0),
            "buried_share": _round((block.get("buriedPct") or 0) / 100.0),
            "air_exposed_share": _round((block.get("airPct") or 0) / 100.0),
            "cave_share_of_air": _round(
                (block.get("caveShareOfAirPct") or 0) / 100.0
            ),
            "both_air_share": _round((block.get("bothAirPct") or 0) / 100.0),
            "unknown_share": _round((block.get("unknownPct") or 0) / 100.0),
            "sample_blocks": int(count),
            "reliable": bool(block.get("reliable")),
        }
        result.rows.append(
            WorldStat(
                pack_version=pack,
                scope_level="dimension",
                dimension=dimension,
                biome="",
                stat_type="block_exposure",
                subject=block_id,
                condition="",
                value=value,
                sample_size=chunks,
                confidence=confidence,
                derived_from=("skyAirPct", "caveAirPct", "waterPct", "buriedPct"),
                provenance=provenance,
                note=(
                    "6 面邻居判定：天空/洞穴空气/水/埋着 四分；"
                    "caveAirPct 等分母是该方块个数，cave_share_of_air 分母是贴空气的个数"
                ),
            )
        )
        result.imported["block_exposure"] = (
            result.imported.get("block_exposure", 0) + 1
        )
