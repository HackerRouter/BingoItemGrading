"""交易事实 → `trade_offer` 统计行。

## 两层数据

`facts/trade.jsonl` 有两种 `layer`：

- **`offer`**（391 条）：单条报价，带 `wants` / `gives` / `meta.max_uses` / `trade`（报价 ID）；
- **`set`**（65 条）：一个职业某一级的报价**集合**，只有 `trades_ref: "#minecraft:armorer/level_1"`，
  指向 `minecraft:villager_trade` 注册表里的标签，要展开才知道具体是哪几条报价。

所以本模块必须拿到标签表（`bingo_grading.tags.TagSet`）才能把 set 补全。展开失败的 set 计入
`unresolved`，不静默当成空。

## 为什么一个 subject 存整组报价而不是一行一条

「某职业某等级能给的东西」是一个整体：多条报价共用同一批村民与交易次数上限，
难度要用**最小代价**那条，而不是把几条都算上。所以 `subject = <profession>/<level>`，
`value.offers` 是一组，由调用方选。

## 同一组里有多条等价交易

例：`farmer/1` 收小麦 20 / 甜菜根 15 / 胡萝卜 22 / 马铃薯 26 都能换 1 绿宝石。
四条都保留，`offer_count` 是条数——选最便宜那条是调用方的事，不是数据的事。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..model import WorldStat

TRADE_REGISTRY = "minecraft:villager_trade"

# vanilla `VillagerTrade` 的 codec 默认值：原始 `villager_trade/*.json` **省略**
# `max_uses` / `xp` 时用这两档（`Codec.INT.optionalFieldOf("max_uses", 4)` /
# `optionalFieldOf("xp", 1)`）。上游 RA 只透传文档里真有的键——那是**对的**，
# 所以默认值必须在下游补，不能指望数据里有。
# 实测 391 条 `offer` 里 266 条带 `xp`（2–30）、374 条带 `max_uses`，其余就是走默认。
DEFAULT_MAX_USES = 4
DEFAULT_XP = 1.0


class TradeError(ValueError):
    """交易事实不可用。"""


def _count(value: object) -> int:
    """报价数量：整数，或 `{min, max}` 区间。

    区间是附魔类报价的真实形状（同一本书的价格随附魔等级浮动，vanilla 5–64）。
    取区间中点当期望——与 `loot/expect.py` 的期望口径一致。**绝不退回 1**：
    把 5–64 的报价当成 1 个，会让附魔书的路线便宜几十倍，比缺席更糟。
    """
    if isinstance(value, bool):
        return 1
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, dict):
        low, high = value.get("min"), value.get("max")
        if isinstance(low, (int, float)) and isinstance(high, (int, float)):
            # 中点向上取整：`round()` 在 .5 上走银行家舍入，结果依赖奇偶，
            # 写死 +0.5 更可预测。
            return int((float(low) + float(high)) / 2 + 0.5)
        if isinstance(low, (int, float)):
            return int(low)
    return 1


def _item(node: object) -> dict | None:
    """`{id, count}` 或 `{items, tags}` 形式的物品说明 → 统一形状。"""
    if not isinstance(node, dict):
        return None
    ident = node.get("id")
    if not isinstance(ident, str):
        return None
    return {"id": ident, "count": _count(node.get("count"))}


def _want_items(node: object) -> list[dict]:
    """`wants` 归一化成列表。

    26.3 的 RA 输出把 `wants` 统一成**数组**（`[{id, count}, ...]`，主槽位即使
    只有一项也是长度 1 的数组）；更早的输出是单个对象。两种都接：漏掉数组形状
    会让**全部** 391 条报价解析失败（`_item` 对 list 返回 None），整层交易凭空消失。
    """
    if isinstance(node, list):
        return [item for item in (_item(entry) for entry in node) if item]
    single = _item(node)
    return [single] if single else []


def _offer(payload: dict) -> dict | None:
    gives = _item(payload.get("gives"))
    wants = _want_items(payload.get("wants"))
    if gives is None or not wants:
        return None
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    uses = meta.get("max_uses")
    xp = meta.get("xp")
    offer = {
        "wants": wants,
        "gives": gives,
        # 省略时不是「未知」，而是游戏用默认值。留 `None` 会让下游升级模型
        # 以为这条报价刷不了，直接丢掉一半候选。
        "max_uses": int(uses) if isinstance(uses, (int, float)) else DEFAULT_MAX_USES,
        "xp": float(xp) if isinstance(xp, (int, float)) else DEFAULT_XP,
    }
    extra = payload.get("additional_wants")
    if isinstance(extra, list):
        cleaned = [item for item in (_item(node) for node in extra) if item]
        if cleaned:
            offer["additional_wants"] = cleaned
    trade = payload.get("trade")
    if isinstance(trade, str):
        offer["trade"] = trade

    return offer


def build(
    *,
    facts_path: Path,
    pack_version: str,
    tags: object | None = None,
    provenance: str = "",
) -> tuple[list[WorldStat], dict]:
    """读 `trade.jsonl`，按「职业/等级」聚合报价。"""
    path = Path(facts_path)
    if not path.exists():
        raise TradeError(f"交易事实不存在：{path}")

    offers: dict[str, dict] = {}
    sets: dict[tuple[str, str], dict] = {}
    # 没有等级的职业（流浪商人）→ 它的报价 ID 列表。
    loose: dict[str, list[str]] = {}
    report: dict = {"offers": 0, "sets": 0, "partial": 0, "unresolved": []}

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        if row.get("status") == "partial":
            report["partial"] += 1
        layer = payload.get("layer")
        if layer == "offer":
            trade = payload.get("trade")
            parsed = _offer(payload)
            if isinstance(trade, str) and parsed is not None:
                offers[trade] = parsed
                report["offers"] += 1
                # 有些职业的报价没有等级（流浪商人）：它没有 `set` 层，
                # 只能按职业自己聚一组，否则这批报价一条也进不了图谱。
                profession = payload.get("profession")
                level = payload.get("level")
                if isinstance(profession, str) and not isinstance(level, (int, str)):
                    loose.setdefault(profession, []).append(trade)
        elif layer == "set":
            profession = payload.get("profession")
            level = payload.get("level")
            ref = payload.get("trades_ref")
            if not isinstance(profession, str) or not isinstance(level, (int, str)):
                continue
            key = (profession, str(level))
            entry = sets.setdefault(key, {"refs": [], "profession": profession, "level": str(level)})
            if isinstance(ref, str):
                entry["refs"].append(ref)
            report["sets"] += 1

    rows: list[WorldStat] = []
    for (profession, level), entry in sorted(sets.items()):
        members: list[str] = []
        for ref in entry["refs"]:
            resolved = ()
            if tags is not None and hasattr(tags, "resolve_ref"):
                resolved = tuple(tags.resolve_ref(ref, registry=TRADE_REGISTRY))
            if not resolved:
                report["unresolved"].append({"profession": profession, "level": level, "ref": ref})
                continue
            members.extend(resolved)
        picked = [offers[trade] for trade in dict.fromkeys(members) if trade in offers]
        if not picked:
            continue
        rows.append(
            WorldStat(
                pack_version=pack_version,
                scope_level="global",
                dimension="",
                biome="",
                stat_type="trade_offer",
                subject=f"minecraft:{profession}/{level}",
                condition="",
                value={
                    "offers": sorted(picked, key=lambda item: item["trade"]),
                    "offer_count": len(picked),
                    "trades_ref": sorted(set(entry["refs"])),
                },
                sample_size=len(picked),
                confidence="high",
                derived_from=("trade.offer", "trade.set", "tag.villager_trade"),
                provenance=provenance,
                note=(
                    "一个职业/等级的全部报价；多条等价交易都保留，选最便宜那条由调用方决定"
                ),
            )
        )

    # 没有等级的报价（流浪商人）：没有 `set` 层可展开，整批就是一个组。
    # subject 用 `minecraft:<profession>`，与 `classify.subject_of` 的口径一致。
    for profession, trades in sorted(loose.items()):
        picked = [offers[trade] for trade in dict.fromkeys(trades) if trade in offers]
        if not picked:
            continue
        rows.append(
            WorldStat(
                pack_version=pack_version,
                scope_level="global",
                dimension="",
                biome="",
                stat_type="trade_offer",
                subject=f"minecraft:{profession}",
                condition="",
                value={
                    "offers": sorted(picked, key=lambda item: item["trade"]),
                    "offer_count": len(picked),
                    "trades_ref": [],
                },
                sample_size=len(picked),
                confidence="high",
                derived_from=("trade.offer",),
                provenance=provenance,
                note=(
                    "该职业的报价没有等级划分，按职业聚成一组；"
                    "出现频率由玩家遭遇决定，不是村庄那种「去一趟就有」"
                ),
            )
        )

    report["rows"] = len(rows)
    return rows, report