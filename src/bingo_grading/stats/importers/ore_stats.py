"""读上游 `ore-stats` 系列产物（schemaVersion 2，按维度分文件）。

## 形状

`ore-stats.json` 是索引，`resultFiles` 给出「维度 → 文件名」；
真正的数据在 `ore-stats.<dimension>.json` 里：

```
result.<dim>:
  chunks, totalColumns, minChunks, minOreSamples, reliableBiomes,
  exposureBlockList, bulkBlockList,
  biomes[]:
    id, columns, chunkEquivalent, chunks, reliable, areaFraction,
    exposure: { <block>: {count, avgPerChunk, airExposed, avgAirExposed, ...} },
    bulk:     { <block>: {count, avgPerChunk} },
    sections: { <block>: [...] }
  sectionProfiles: { <block>: {kind: exposure|bulk, count, sections: [...]} }
```

## 映射

| 来源 | 落成 | 说明 |
|---|---|---|
| `biomes[].exposure[block]` | `ore_density` | 只取密度，**不含暴露**（ADR 0012） |
| `biomes[].exposure[block]` | `ore_exposure` | 暴露分解，群系级 |
| `biomes[].bulk[block]` | `block_density` | 非矿石方块（紫颂植物、黑曜石等） |

`bulk` 与 `exposure` 是上游刻意分开的：`exposure` 类逐面判定暴露，
`bulk` 类只数数量（因为它们天然生在开阔处，算暴露没信息量）。本模块按这个
区分分派统计类型，不合并。
"""

from __future__ import annotations

import json
from pathlib import Path

ORE_STATS_INDEX = "ore-stats.json"
ORE_STATS_PATTERN = "ore-stats.*.json"

# 与本项目其它导入器一致：只认 schemaVersion 2。
SUPPORTED_SCHEMA = 2


def _validate(doc: dict, path: Path) -> None:
    """校验单个 ore-stats 文件。失败抛 `ValueError`，由调用方转成自己的错误类型。"""
    version = doc.get("schemaVersion")
    if version != SUPPORTED_SCHEMA:
        raise ValueError(f"{path} 的 schemaVersion={version!r}，只认 {SUPPORTED_SCHEMA}")
    if doc.get("ok") is False:
        raise ValueError(f"{path} 标记 ok=false，该分析器运行失败")


def dimension_payloads(run_dir: Path) -> dict[str, dict]:
    """返回 `维度 → ore-stats 的 result[维度]`。找不到时返回空字典。"""
    run_dir = Path(run_dir)
    out: dict[str, dict] = {}

    index_path = run_dir / ORE_STATS_INDEX
    files: list[Path] = []
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            index = {}
        _validate(index, index_path)
        files_map = index.get("resultFiles") or {}
        for name in files_map.values():
            if isinstance(name, str):
                candidate = run_dir / name
                if candidate.exists():
                    files.append(candidate)
        # 索引自身的 result 也收（可能带内联数据）
        for dimension, payload in (index.get("result") or {}).items():
            if isinstance(payload, dict):
                out[dimension] = payload

    if not files:
        files = sorted(run_dir.glob(ORE_STATS_PATTERN))

    for path in files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        _validate(doc, path)
        for dimension, payload in (doc.get("result") or {}).items():
            if isinstance(payload, dict):
                out[dimension] = payload
    return out
