"""矿石：群系级密度与暴露面份额。"""

from __future__ import annotations


from pathlib import Path
from ...model import WorldStat
from .model import ImportResult, _provenance, _round, confidence_for




def _import_ore_stats(
    payloads: dict[str, dict],
    result: ImportResult,
    pack: str,
    dimension: str,
    run_dir: Path,
) -> None:
    """群系级矿石/方块统计。

    上游 `ore-stats` 把方块分成两类，本模块按类别分派：

    - `exposure`：逐面判定暴露的方块（矿石），同时产 `ore_density` 与 `ore_exposure`。
    - `bulk`：只数数量的方块（紫颂植物、黑曜石），产 `block_density`。

    `ore_density` 不含暴露分量，理由见 ADR 0012：玩家会专程进该群系挖矿道。
    """
    payload = payloads.get(dimension)
    if payload is None:
        result.gaps["unmapped_provenance"].append(
            f"ore-stats 没有维度 {dimension!r} 的结果；现有 {sorted(payloads)}"
        )
        return

    provenance = _provenance(run_dir, f"ore-stats.{dimension}.json")
    min_chunks = payload.get("minChunks")

    for biome in payload.get("biomes") or []:
        biome_id = biome.get("id")
        if not isinstance(biome_id, str):
            result.gaps["unmapped_provenance"].append(f"群系条目缺 id：{biome}")
            continue
        chunks = int(biome.get("chunks") or 0)
        equivalent = biome.get("chunkEquivalent")
        reliable = biome.get("reliable")
        confidence = confidence_for(chunks)
        if reliable is False:
            confidence = "low"

        sections = biome.get("sections") or {}
        for block_id, cell in (biome.get("exposure") or {}).items():
            _density_row(
                result, pack, dimension, biome_id, block_id, cell,
                chunks=chunks, equivalent=equivalent, reliable=reliable,
                confidence=confidence, provenance=provenance,
                stat_type="ore_density",
                sections=sections,
                kind="exposure",
                note=(
                    "群系级分布：分母为该群系等效区块数（地表列数/256），"
                    "不是总区块数；不含暴露判定"
                ),
            )
            exposure_cell = dict(cell)
            if exposure_cell.get("count") is not None:
                _exposure_row(
                    result, pack, dimension, biome_id, block_id, exposure_cell,
                    chunks=chunks, confidence=confidence, provenance=provenance,
                )

        for block_id, cell in (biome.get("bulk") or {}).items():
            _density_row(
                result, pack, dimension, biome_id, block_id, cell,
                chunks=chunks, equivalent=equivalent, reliable=reliable,
                confidence=confidence, provenance=provenance,
                stat_type="block_density",
                sections=sections,
                kind="bulk",
                note=(
                    "群系级分布（非矿石方块）：上游按 bulk 类只数数量，"
                    "不做暴露判定；分母为该群系等效区块数"
                ),
            )

    if min_chunks is not None:
        result.gaps.setdefault("notes", []).append(
            f"ore-stats 的 reliable 阈值为 chunks >= {min_chunks}"
        )




def _density_row(
    result: ImportResult,
    pack: str,
    dimension: str,
    biome_id: str,
    block_id: str,
    cell: dict,
    *,
    chunks: int,
    equivalent,
    reliable,
    confidence: str,
    provenance: str,
    stat_type: str,
    sections,
    kind: str,
    note: str,
) -> None:
    """写一行 `ore_density` / `block_density`。"""
    count = cell.get("count")
    density = cell.get("avgPerChunk")
    if count is None or density is None:
        return

    value: dict = {"per_chunk_density": _round(density)}
    if equivalent is not None:
        value["equivalent_chunks"] = _round(equivalent, 2)
    value["chunks"] = chunks
    value["total_blocks"] = int(count)
    if isinstance(reliable, bool):
        value["reliable"] = reliable
    if isinstance(sections, list) and sections:
        by_section: dict[str, dict] = {}
        for section in sections:
            if not isinstance(section, dict):
                continue
            y = section.get("yRange") or []
            if len(y) != 2:
                continue
            # 每个纵段里再按方块分（`exposure` / `bulk`），取本方块那一条。
            cell_in_section = (section.get(kind) or {}).get(block_id)
            if not isinstance(cell_in_section, dict):
                continue
            by_section[str(y[0])] = {
                "y_range": list(y),
                "count": int(cell_in_section.get("count") or 0),
                "per_chunk": _round(cell_in_section.get("avgPerChunk") or 0),
            }
        if by_section:
            value["by_section"] = dict(sorted(by_section.items(), key=lambda kv: int(kv[0])))

    result.rows.append(
        WorldStat(
            pack_version=pack,
            scope_level="biome",
            dimension=dimension,
            biome=biome_id,
            stat_type=stat_type,
            subject=block_id,
            condition="",
            value=value,
            sample_size=chunks,
            confidence=confidence,
            derived_from=("avgPerChunk",),
            provenance=provenance,
            note=note,
        )
    )
    result.imported[stat_type] = result.imported.get(stat_type, 0) + 1




def _exposure_row(
    result: ImportResult,
    pack: str,
    dimension: str,
    biome_id: str,
    block_id: str,
    cell: dict,
    *,
    chunks: int,
    confidence: str,
    provenance: str,
) -> None:
    """写一行群系级 `ore_exposure`。只给「顺路能碰到多少」用。"""
    if not cell.get("count"):
        return
    total = cell.get("avgPerChunk") or 0
    air_pct = cell.get("airPct")
    value = {
        "air_exposed": _round(cell.get("avgAirExposed") or 0),
        "water_exposed": _round(cell.get("avgWaterExposed") or 0),
        "buried": _round(cell.get("avgBuried") or 0),
        "per_chunk_density": _round(total),
        "air_exposed_share": _round((air_pct or 0) / 100.0),
    }
    result.rows.append(
        WorldStat(
            pack_version=pack,
            scope_level="biome",
            dimension=dimension,
            biome=biome_id,
            stat_type="ore_exposure",
            subject=block_id,
            condition="",
            value=value,
            sample_size=chunks,
            confidence=confidence,
            derived_from=("airPct", "avgAirExposed", "avgPerChunk"),
            provenance=provenance,
            note=(
                "群系级暴露：air_exposed 含 cave_air，不能用来判断「地表是否露出」"
                "（ADR 0014）；本行只用于「顺路能碰到多少」"
            ),
        )
    )
    result.imported["ore_exposure"] = result.imported.get("ore_exposure", 0) + 1
