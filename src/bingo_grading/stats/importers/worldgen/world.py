"""岩浆湖、纵段方块直方图、实体普查。"""

from __future__ import annotations


from pathlib import Path
from ...model import WorldStat
from .model import ENTITY_FILE, HISTOGRAM_FILE, HISTOGRAM_MIN_PER_CHUNK, ImportResult, LAVA_FILE, LAVA_SUBJECT, SECTION_VOLUME, WET_BLOCKS, _provenance, _require_dimension, _round, confidence_for




def _import_lava(
    doc: dict, result: ImportResult, pack: str, dimension: str, run_dir: Path
) -> None:
    """地表岩浆湖 → 结构密度。地下岩浆面积无间距，不导入。"""
    payload = _require_dimension(doc, dimension, LAVA_FILE)
    chunks = int(payload.get("chunks") or 0)
    surface = payload.get("surface") or {}
    spacing = surface.get("spacing") or {}
    distance = spacing.get("meanNNBlocks")
    if distance is None:
        result.gaps["unmapped_provenance"].append(f"{LAVA_SUBJECT}: 无最近距离测量")
        return

    value: dict = {
        "expected_nearest_distance": _round(distance),
        "structure_set": LAVA_SUBJECT,
        "structure_ids": ["minecraft:lava_lake"],
        "biome_conditions": [],
    }
    mean_chunks = spacing.get("meanNNChunks")
    if mean_chunks is not None:
        # 随机放置下最近邻距离约半个网格边长，故网格约为两倍。
        value["spacing"] = round(mean_chunks * 2)
    if spacing.get("medianNNBlocks") is not None:
        value["median_nearest_distance"] = _round(spacing["medianNNBlocks"])
    if spacing.get("count") is not None:
        value["observations"] = int(spacing["count"])
    groups = surface.get("groups") or {}
    if groups.get("avgSize") is not None:
        value["mean_size"] = groups["avgSize"]
    density = (surface.get("density") or {}).get("lakesPer1000LandChunks")
    if density is not None:
        value["density_per_1000_chunks"] = density

    result.rows.append(
        WorldStat(
            pack_version=pack,
            scope_level="dimension",
            dimension=dimension,
            biome="",
            stat_type="structure_density",
            subject=LAVA_SUBJECT,
            condition="",
            value=value,
            sample_size=int(spacing.get("count") or 0),
            confidence="low",
            derived_from=("spacing.meanNNBlocks", "groups.avgSize"),
            provenance=_provenance(run_dir, LAVA_FILE),
            note="地表岩浆湖按离散散布特征测量；只统计陆地区块，水域已扣除",
        )
    )
    result.imported["structure_density"] = result.imported.get("structure_density", 0) + 1




def _import_block_histogram(
    doc: dict, result: ImportResult, pack: str, dimension: str, run_dir: Path
) -> None:
    """逐区段方块直方图 → `block_density`（维度级）。

    回答「任意方块的每区块数量」，覆盖非矿石方块（粘土、干草块、小麦作物、
    原木等）。`ore-stats` 只管矿石，这是它的补充。

    只写维度级：直方图本身没有群系轴。下游按 `global → dimension` 回退能取到。

    数量级很低的方块（< `HISTOGRAM_MIN_PER_CHUNK`）跳过，并在缺口报告里记数。
    保留它们只会让「几千区块挖一块」这类无意义结果挤进候选。
    """
    payload = _require_dimension(doc, dimension, HISTOGRAM_FILE)
    chunks = int(payload.get("chunks") or 0)
    if chunks <= 0:
        result.gaps["unmapped_provenance"].append(f"{HISTOGRAM_FILE}: {dimension} 无区块")
        return
    provenance = _provenance(run_dir, HISTOGRAM_FILE)
    confidence = confidence_for(chunks)

    # 按方块累加：直方图给了每个纵段的均值，全高合计才是每区块总量。
    totals: dict[str, float] = {}
    by_section: dict[str, dict[str, dict]] = {}
    section_fill: dict[str, dict] = {}
    for section in payload.get("sections") or []:
        if not isinstance(section, dict):
            continue
        y_range = section.get("yRange") or []
        if len(y_range) != 2:
            continue
        low, high = int(y_range[0]), int(y_range[1])
        blocks = [b for b in (section.get("blocks") or []) if isinstance(b, dict)]
        total = section.get("avgTotal")
        if not isinstance(total, (int, float)):
            # `avgTotal` 理论上等于各方块 avg 之和；缺字段时自己加总，
            # 免得少一个字段就整段丢失敞闭判据。
            total = sum(float(b.get("avg") or 0.0) for b in blocks)
        fill = _round(float(total) / SECTION_VOLUME)
        wet = 0.0
        for block in blocks:
            block_id = block.get("id")
            average = block.get("avg")
            if not isinstance(block_id, str) or average is None:
                continue
            average = float(average)
            if block_id in WET_BLOCKS:
                wet += average
            totals[block_id] = totals.get(block_id, 0.0) + average
            per_section = by_section.setdefault(block_id, {})
            per_section[str(low)] = {
                "y_range": [low, high],
                "count": int(round(average * chunks)),
                "per_chunk": _round(average),
                "section_fill": fill,
            }
        if blocks:
            # 段属性，与具体方块无关：下游要知道的是「这段敞开不敞开」。
            # `fill_dry` 把水与岩浆扣掉——海底沙所在段的 fill 有 40% 是水，
            # 不扣就会把水下露头误判成埋着。
            section_fill[str(low)] = {
                "y_range": [low, high],
                "fill": fill,
                "fill_dry": _round((float(total) - wet) / SECTION_VOLUME),
            }

    skipped = 0
    for block_id, total in sorted(totals.items()):
        if total < HISTOGRAM_MIN_PER_CHUNK:
            skipped += 1
            continue
        value: dict = {
            "per_chunk_density": _round(total),
            "chunks": chunks,
            # 直方图无需暴露方块「个数」与密度之外的量：total_blocks 由均值 × 区块数算。
            "total_blocks": int(round(total * chunks)),
        }
        sections = by_section.get(block_id) or {}
        if sections:
            value["by_section"] = dict(sorted(sections.items(), key=lambda kv: int(kv[0])))
        result.rows.append(
            WorldStat(
                pack_version=pack,
                scope_level="dimension",
                dimension=dimension,
                biome="",
                stat_type="block_density",
                subject=block_id,
                condition="",
                value=value,
                sample_size=chunks,
                confidence=confidence,
                derived_from=("sections[].blocks[].avg",),
                provenance=provenance,
                note=(
                    "任意方块的每区块数量（全高合计，来自逐区段直方图）；"
                    "分母为扫描区块数，无群系轴"
                ),
            )
        )
        result.imported["block_density"] = result.imported.get("block_density", 0) + 1

    if skipped:
        result.gaps.setdefault("notes", []).append(
            f"{dimension}: 直方图中 {skipped} 种方块每区块不足 "
            f"{HISTOGRAM_MIN_PER_CHUNK}，未导入"
        )

    # 段表单独成行：下游要按「某方块主段的上面那一段」查敞开程度，
    # 而 `by_section` 只含该方块自己出现的段，查不到别人的段。
    if section_fill:
        result.rows.append(
            WorldStat(
                pack_version=pack,
                scope_level="dimension",
                dimension=dimension,
                biome="",
                stat_type="section_fill",
                subject="",
                condition="",
                value={
                    "sections": dict(
                        sorted(section_fill.items(), key=lambda kv: int(kv[0]))
                    ),
                    "chunks": chunks,
                },
                sample_size=chunks,
                confidence=confidence,
                derived_from=("sections[].avgTotal", "blocks[].avg"),
                provenance=provenance,
                note=(
                    "逐纵段的实心占比：fill = avgTotal/4096，fill_dry 扣掉水与岩浆；"
                    "用来判断某位置上下是否敞开的代理量"
                ),
            )
        )
        result.imported["section_fill"] = result.imported.get("section_fill", 0) + 1




def _import_entities(
    doc: dict, result: ImportResult, pack: str, dimension: str, run_dir: Path
) -> None:
    payload = _require_dimension(doc, dimension, ENTITY_FILE)
    chunks = int(payload.get("chunks") or 0)
    provenance = _provenance(run_dir, ENTITY_FILE)
    for entity_id, cell in (payload.get("byType") or {}).items():
        group = cell.get("group") or {}
        value = {
            "per_chunk": _round(cell.get("perChunk", 0)),
            "chunks_per": None if cell.get("chunksPer") is None else _round(cell["chunksPer"]),
            "groups_per_chunk": _round(group.get("perChunk", 0)),
            "avg_group_size": _round(group.get("avgSize", 0)),
            "avg_y": None if cell.get("avgY") is None else _round(cell["avgY"]),
            "category": cell.get("category", ""),
        }
        result.rows.append(
            WorldStat(
                pack_version=pack,
                scope_level="dimension",
                dimension=dimension,
                biome="",
                stat_type="mob_density",
                subject=entity_id,
                condition="",
                value={key: item for key, item in value.items() if item is not None},
                sample_size=chunks,
                confidence=confidence_for(chunks),
                derived_from=("perChunk", "chunksPer"),
                provenance=provenance,
                note=(
                    "世界生成时放置的实体实测；分母为扫描区块数。"
                    "不含怪物刷新——静态存档没有玩家时怪物不会被触发"
                ),
            )
        )
        result.imported["mob_density"] = result.imported.get("mob_density", 0) + 1
