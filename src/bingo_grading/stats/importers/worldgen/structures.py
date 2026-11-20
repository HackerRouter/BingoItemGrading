"""结构间距。"""

from __future__ import annotations


from pathlib import Path
from ...model import WorldStat
from .model import ImportResult, STRUCTURE_FILE, _provenance, _require_dimension, _round, confidence_for




def _import_structures(
    doc: dict, result: ImportResult, pack: str, dimension: str, run_dir: Path
) -> None:
    from ...model import StatError

    payload = _require_dimension(doc, dimension, STRUCTURE_FILE)
    chunks = int(payload.get("chunks") or 0)
    provenance = _provenance(run_dir, STRUCTURE_FILE)

    for group in payload.get("groups") or []:
        set_id = group.get("set")
        if not isinstance(set_id, str):
            result.gaps["unmapped_provenance"].append(f"结构集合缺失：{group}")
            continue

        configured = group.get("configured") or {}
        trimmed = group.get("trimmed") or {}
        measured = trimmed.get("meanNNBlocks") or group.get("meanNNBlocks")

        value: dict = {}
        derived: list[str] = []
        confidence = confidence_for(chunks)

        if measured is not None:
            value["expected_nearest_distance"] = _round(measured)
            derived.append("meanNNBlocks")
            if group.get("medianNNBlocks") is not None:
                value["median_nearest_distance"] = _round(group["medianNNBlocks"])
        elif isinstance(configured.get("spacingChunks"), (int, float)):
            # 测量样本不足（起点太少）时按间距推导。间距是网格边长，
            # 期望最近距离取半个边长，单位从区块换算成方块。
            value["expected_nearest_distance"] = _round(configured["spacingChunks"] * 16 / 2)
            derived.append("configured.spacingChunks")
            confidence = "low"
        else:
            result.gaps["unmapped_provenance"].append(f"{set_id}: 无最近距离测量，也无配置间距")
            continue

        if isinstance(configured.get("spacingChunks"), (int, float)):
            value["spacing"] = configured["spacingChunks"]
        if isinstance(configured.get("separationChunks"), (int, float)):
            value["separation"] = configured["separationChunks"]

        # 分布尾部：下游可在「期望 / 中位数 / 保守估计」之间切换。
        # 采集侧在样本不足时给 null（不写 0），这里按原样跳过。
        quantiles = group.get("quantiles") or {}
        for key, name in (
            ("p25", "p25_nearest_distance"),
            ("p50", "p50_nearest_distance"),
            ("p75", "p75_nearest_distance"),
            ("p90", "p90_nearest_distance"),
        ):
            amount = quantiles.get(key)
            if isinstance(amount, (int, float)):
                value[name] = _round(amount)
        if isinstance(group.get("varianceNN"), (int, float)):
            value["variance_nearest_distance"] = _round(group["varianceNN"])
        if isinstance(group.get("maxNNBlocks"), (int, float)):
            value["max_nearest_distance"] = _round(group["maxNNBlocks"])
        if isinstance(group.get("minNNBlocks"), (int, float)):
            value["min_nearest_distance"] = _round(group["minNNBlocks"])
        if isinstance(group.get("densityPer1000Chunks"), (int, float)):
            value["density_per_1000_chunks"] = _round(group["densityPer1000Chunks"])
        if group.get("source") == "feature":
            value["source"] = "feature"

        value["structure_set"] = set_id
        if group.get("structureIds"):
            value["structure_ids"] = list(group["structureIds"])
        if group.get("count") is not None:
            value["observations"] = int(group["count"])

        # 群系条件是结构生成的必要条件，但收集侧没有测量；留空并写明。
        value["biome_conditions"] = []

        try:
            stat = WorldStat(
                pack_version=pack,
                scope_level="dimension",
                dimension=dimension,
                biome="",
                stat_type="structure_density",
                subject=set_id,
                condition="",
                value=value,
                sample_size=int(group.get("count") or 0),
                confidence=confidence,
                derived_from=tuple(derived),
                provenance=provenance,
                note="观测样本为该范围内结构起点数；样本少时按配置间距推导",
            )
        except StatError as exc:
            result.gaps["unmapped_provenance"].append(f"{set_id}: {exc}")
            continue

        result.rows.append(stat)
        result.imported["structure_density"] = result.imported.get("structure_density", 0) + 1
