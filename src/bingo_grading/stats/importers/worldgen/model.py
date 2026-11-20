"""共享模型与常量：结果类型、置信度、读文件的底层助手。"""

from __future__ import annotations

import json
import re

from dataclasses import dataclass, field
from pathlib import Path
from ...model import WorldStat



ORE_EXPOSURE_FILE = "ore-exposure.json"


ORE_DENSITY_FILE = "biome-ore.json"


ORE_STATS_INDEX = "ore-stats.json"


BIOME_FILE = "biome-histogram.json"


BIOME_PATCH_FILE = "biome-patch.json"


STRUCTURE_FILE = "structure-spacing.json"


ENTITY_FILE = "entity-census.json"


LAVA_FILE = "lava-lakes.json"


HISTOGRAM_FILE = "section-block-histogram.json"


CAVE_EXPOSURE_FILE = "cave-exposure.json"



# 岩浆湖按「离散散布特征」导入结构密度：它测出了最近距离与规模，
# 正是计算岩浆/黑曜石路线需要的量。
LAVA_SUBJECT = "minecraft:surface_lava_lake"



# 已知存在、但第一版没有对应 `stat_type` 的分析器。列出来是为了让缺口报告
# 明确说「测到了但没接」，而不是让人以为没测。
UNMAPPED_ANALYZERS: dict[str, str] = {}



# 分母 → 置信度。低于第二档记 low。
CONFIDENCE_THRESHOLDS = ((2000, "high"), (300, "medium"))



# v1 的扁平 `result` 无法安全导入。
SUPPORTED_SCHEMA = 2



# 由本项目自己算的统计类型，采集侧不产出，因此不算它「缺测」。
LOOT_STAT_TYPE = "loot_expectation"



DEFAULT_DIMENSION = "minecraft:overworld"




class ImportError_(ValueError):
    """统计产物不可用。"""




@dataclass
class Target:
    """产物的溯源信息。`dataPacks` 决定这批统计属于哪个地形包。"""

    minecraftVersion: str = ""
    levelName: str = ""
    seed: str = ""
    seedMode: str = ""
    serverJarSha256: str = ""
    dataPacks: list[dict] = field(default_factory=list)
    range: dict = field(default_factory=dict)
    generatedAt: str = ""
    run: str = ""

    def as_dict(self) -> dict:
        return {
            "minecraftVersion": self.minecraftVersion,
            "levelName": self.levelName,
            "seed": self.seed,
            "seedMode": self.seedMode,
            "serverJarSha256": self.serverJarSha256,
            "dataPacks": self.dataPacks,
            "range": self.range,
            "generatedAt": self.generatedAt,
            "run": self.run,
        }

    def pack_fingerprint(self) -> str:
        """地形包指纹：启用包的内容哈希拼起来。无数据包时为空串。"""
        hashes = [pack.get("sha256", "") for pack in self.dataPacks if pack.get("enabled", True)]
        return "+".join(sorted(h for h in hashes if h))




@dataclass
class ImportResult:
    run: str
    pack_version: str
    target: Target = field(default_factory=Target)
    rows: list[WorldStat] = field(default_factory=list)
    imported: dict[str, int] = field(default_factory=dict)
    gaps: dict[str, list[str]] = field(default_factory=dict)
    unmapped_analyzers: dict[str, str] = field(default_factory=dict)
    dimensions: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "run": self.run,
            "pack_version": self.pack_version,
            "rows": len(self.rows),
            "dimensions": self.dimensions,
            "by_stat_type": dict(sorted(self.imported.items())),
            "target": {
                "minecraftVersion": self.target.minecraftVersion,
                "seed": self.target.seed,
                "seedMode": self.target.seedMode,
                "dataPacks": [pack.get("id") for pack in self.target.dataPacks],
                "packFingerprint": self.target.pack_fingerprint(),
                "serverJarSha256": self.target.serverJarSha256,
            },
            "gaps": {key: value[:10] for key, value in self.gaps.items()},
            "gap_counts": {key: len(value) for key, value in self.gaps.items()},
            "unmapped_analyzers": self.unmapped_analyzers,
        }




def confidence_for(sample_size: int) -> str:
    for threshold, level in CONFIDENCE_THRESHOLDS:
        if sample_size >= threshold:
            return level
    return "low"




def guess_minecraft_version(run_dir: Path) -> str | None:
    """先从 `summary.json` 的 `target.minecraftVersion` 取，退回 world 路径。"""
    summary = Path(run_dir) / "summary.json"
    if not summary.exists():
        return None
    try:
        doc = json.loads(summary.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    target = doc.get("target") or {}
    version = target.get("minecraftVersion")
    if isinstance(version, str) and version:
        return version

    world = doc.get("world")
    if not isinstance(world, str):
        return None
    match = re.search(r"[/\\]\.server[/\\]([^/\\]+)[/\\]", world)
    return match.group(1) if match else None




def _read(run_dir: Path, name: str) -> dict | None:
    path = run_dir / name
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ImportError_(f"{path} 不是合法 JSON：{exc}") from exc
    if not isinstance(doc, dict):
        raise ImportError_(f"{path} 顶层不是对象")

    version = doc.get("schemaVersion")
    if version != SUPPORTED_SCHEMA:
        raise ImportError_(
            f"{path} 的 schemaVersion={version!r}，本程序只认 {SUPPORTED_SCHEMA}。"
            "旧形态的 result 是扁平结构、维度信息丢失，无法安全导入；"
            "请用新版采集侧重跑一次。"
        )
    if doc.get("ok") is False:
        raise ImportError_(f"{path} 标记 ok=false，该分析器运行失败")
    if not isinstance(doc.get("result"), dict):
        raise ImportError_(f"{path} 缺 result 对象")
    return doc




def _round(value: float | int, digits: int = 4) -> float:
    return round(float(value), digits)




def _dimensions_of(doc: dict) -> list[str]:
    """`result` 的键就是维度 ID（v2 契约）。"""
    return sorted(doc["result"].keys())




def _require_dimension(doc: dict, dimension: str, path: str) -> dict:
    payload = doc["result"].get(dimension)
    if payload is None:
        raise ImportError_(
            f"{path} 没有维度 {dimension!r} 的结果；该文件含 {_dimensions_of(doc)}"
        )
    return payload




def _results_of(*docs) -> list[dict]:
    """把多个分析器文档的 `result` 转成「维度 → 载荷」的映射，供并集使用。"""
    out: list[dict] = []
    for doc in docs:
        if doc is None:
            continue
        result = doc.get("result") or {}
        out.append({dimension: None for dimension in result})
    return out




def _all_dimensions(payloads: list[dict]) -> list[str]:
    seen: set[str] = set()
    for payload in payloads:
        seen.update(payload)
    return sorted(seen)




def _provenance(run_dir: Path, file: str) -> str:
    return f"{run_dir.name}/{file}"




# 直方图里数量太少的方块不导入。
#
# 原先是 0.01（每区块百分之一），把稀有但**真实存在**的方块全滤掉了：
# `bee_nest` 在森林群系实测 0.00213/区块（约每 470 区块一个），汇总到维度级更小，
# 于是「取蜜」这条来源整条缺席。0.01 挡得住的是「几千区块挖一块」那种没有
# 路线意义的东西，而 `bee_nest` 是「林子里走一圈就能看到」——两者量级不同。
# 取 1e-4：低于它的确实是统计噪声，高于它的都值得让下游自己判断。
HISTOGRAM_MIN_PER_CHUNK = 1e-4



# 一个纵段的体积（16×16×16）。直方图的 `avgTotal` 是「该段每区块实心方块数」，
# 除以它才是**该段的实心占比**——下游用它判断「这个方块所在的段是不是敞开的」。
SECTION_VOLUME = 4096.0



# 算「干填充率」时要扣掉的流体：海水会把海底方块所在段的占比撑到 96%，
# 不扣就会把水下露头（沙、粘土、砾石）误判成埋在地下。
WET_BLOCKS = ("minecraft:water", "minecraft:lava")
