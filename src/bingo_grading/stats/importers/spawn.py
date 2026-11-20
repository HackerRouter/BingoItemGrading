"""RA 的 `spawn_tables.jsonl` → `mob_spawn` 统计行。

## 为什么需要它

C17 撤回了「敌对生物密度」这项采集需求——密度依赖玩家活动（mob cap、光照、
与玩家的距离），静态扫描给不出可信值。但**刷怪规则本身是静态事实**：
哪个群系 / 结构 / 事件会刷什么、权重多少、一次刷几只。`spawn_tables.jsonl`
就是这份事实。

两张表分工：

| stat_type | 回答什么问题 | 口径 |
|---|---|---|
| `mob_density` | 在某群系里走一段会遇到几只 | 实测（只对被动生物可信） |
| `mob_spawn` | 在某个 holder 里待着会刷出什么 | 刷怪规则的静态值 |

## holder 的种类

`holder_kind` 有五类，下游的用法不同：

- `biome`：在该群系里自然刷。要乘上「玩家在那儿待多久」。
- `structure`：结构专属刷怪（`monument` 刷守卫者、`fortress` 刷凋灵骷髅）。
- `structure_template`：模板里挂的刷怪配置（堡垒的岩浆怪）。
- `raid`：袭击波次（唤魔者、卫道士、劫掠兽）。
- `trial_spawner`：试炼大厅的刷怪笼（`ticks_between_spawn` 在
  `facts/spawner_config.jsonl` 里，不在这张表）。

## 行怎么落

主键是 `(stat_type, subject, dimension, biome, condition)`。同一个生物会在多个
holder 下各有一条，所以 `condition` 写 `holder=<holder>`；`holder_kind == "biome"`
时再把群系填进 `biome` 字段，那样「末影人在恶地」与「末影人在竹林」是两行，
可以按群系查，也可以按生物聚合。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..model import WorldStat

SPAWN_TABLES = "spawn_tables.jsonl"


class SpawnError(ValueError):
    """刷怪表不可用。"""


def _biome_of(holder: str, holder_kind: str) -> str:
    """`biome:minecraft:badlands` → `minecraft:badlands`；非群系 holder 返回空串。"""
    if holder_kind != "biome":
        return ""
    _, _, rest = holder.partition(":")
    return rest


def build(
    *,
    tables_path: Path,
    pack_version: str,
    provenance: str = "",
) -> tuple[list[WorldStat], dict]:
    """读 `spawn_tables.jsonl`，每条 (holder, entity) 落一行。"""
    path = Path(tables_path)
    if not path.exists():
        raise SpawnError(f"刷怪表不存在：{path}")

    rows: list[WorldStat] = []
    report: dict = {"rows": 0, "by_kind": {}, "entities": set(), "holders": set()}
    seen: set[tuple[str, str, str, str]] = set()
    # 袭击是「波次配置」而不是权重抽样，同一个生物会在很多波里各有一条。
    # 下游要的是「一整场袭击会出几只」，所以按 (holder, entity) 先加总。
    raid_totals: dict[tuple[str, str], dict] = {}

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        entity = record.get("entity")
        holder = record.get("holder")
        holder_kind = record.get("holder_kind")
        weight = record.get("weight")
        count_max = record.get("count_max")
        if not isinstance(entity, str) or not isinstance(holder, str):
            continue
        if not isinstance(holder_kind, str):
            continue
        # 两种形态：`biome` / `structure` / `trial_spawner` 用 `weight` 抽样；
        # `raid` 用 `wave` + `count_min/max` 做确定性的波次配置，没有权重。
        has_weight = isinstance(weight, (int, float))
        has_count = isinstance(count_max, (int, float))
        if not has_weight and not has_count:
            continue
        if holder_kind == "raid":
            entry = raid_totals.setdefault(holder, {}).setdefault(
                entity, {"min": 0.0, "max": 0.0, "waves": 0, "per_wave": {}}
            )
            low = record.get("count_min")
            wave = record.get("wave")
            entry["min"] += float(low) if isinstance(low, (int, float)) else 0.0
            entry["max"] += float(count_max) if has_count else 0.0
            entry["waves"] += 1
            if isinstance(wave, int) and has_count and count_max:
                # 每波明细不丢：下游要「打到能拿到目标为止」，而不是整场平摊。
                entry["per_wave"][str(wave)] = float(count_max)
            continue
        biome = _biome_of(holder, holder_kind)
        key = (entity, holder, biome, str(record.get("wave") or ""))
        if key in seen:
            # 同一条规则出现两次只留第一份；重复计入权重会让它被刷得更勤。
            continue
        seen.add(key)
        value: dict = {
            "holder": holder,
            "holder_kind": holder_kind,
        }
        if has_weight:
            value["weight"] = float(weight)
        for source, target in (
            ("count_min", "count_min"),
            ("count_max", "count_max"),
            ("category", "category"),
            ("requires", "requires"),
            ("wave", "wave"),
        ):
            amount = record.get(source)
            if amount is not None:
                if target in ("count_min", "count_max") and isinstance(
                    amount, (int, float)
                ):
                    value[target] = float(amount)
                elif isinstance(amount, str):
                    value[target] = amount
                elif isinstance(amount, dict):
                    value[target] = amount
        rows.append(
            WorldStat(
                pack_version=pack_version,
                # 刷怪表不带维度（`biome:minecraft:badlands` 里没有维度），
                # 而 biome 层要求 dimension 非空，所以统一落 global 层，
                # 群系留在 `condition` 的 holder 里。要按群系查就过滤 condition。
                scope_level="global",
                dimension="",
                biome="",
                stat_type="mob_spawn",
                subject=entity,
                condition=f"holder={holder}",
                value=value,
                sample_size=1,
                confidence="high",
                derived_from=("spawn_table",),
                provenance=provenance,
                note="刷怪规则的静态值；密度要看 mob_density，两者口径不同",
            )
        )
        report["rows"] += 1
        report["by_kind"][holder_kind] = report["by_kind"].get(holder_kind, 0) + 1
        report["entities"].add(entity)
        report["holders"].add(holder)

    for holder, mobs in sorted(raid_totals.items()):
        for entity, entry in sorted(mobs.items()):
            value = {
                "holder": holder,
                "holder_kind": "raid",
                "count_min": round(entry["min"], 3),
                "count_max": round(entry["max"], 3),
                "wave": entry["waves"],
                "requires": "assume:raid",
            }
            if entry["per_wave"]:
                value["wave_counts"] = dict(
                    sorted(entry["per_wave"].items(), key=lambda kv: int(kv[0]))
                )
            rows.append(
                WorldStat(
                    pack_version=pack_version,
                    scope_level="global",
                    dimension="",
                    biome="",
                    stat_type="mob_spawn",
                    subject=entity,
                    condition=f"holder={holder}",
                    value=value,
                    sample_size=entry["waves"],
                    confidence="high",
                    derived_from=("spawn_table",),
                    provenance=provenance,
                    note="一整场袭击的合计（各波次加总）；`wave_counts` 是每波明细",
                )
            )
            report["rows"] += 1
            report["by_kind"]["raid"] = report["by_kind"].get("raid", 0) + 1
            report["entities"].add(entity)
            report["holders"].add(holder)

    report["entities"] = sorted(report["entities"])
    report["holders"] = sorted(report["holders"])
    report["entity_count"] = len(report["entities"])
    report["holder_count"] = len(report["holders"])
    return rows, report
