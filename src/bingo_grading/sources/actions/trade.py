"""村民交易：报价、等级爬升、职业能力。"""

from __future__ import annotations

import math
from bingo_grading import gamedata
from bingo_grading.case.context import CaseContext
from bingo_grading.case.sources import seconds
from bingo_grading.plan import Action, Requirement
from bingo_grading.plan.actions import MODE_ONCE, MODE_PER_USE
from bingo_grading.sources import index as source_index

from .capabilities import _ensure_capability
from .common import WANDERING_TRADER, WANDERING_TRADER_CAP, _short
from .graph import GraphActions




def _want_entries(value: object) -> tuple[dict, ...]:
    """报价槽位归一：上游有时给数组，有时给单个对象（附魔书那条就是对象）。"""
    if isinstance(value, dict):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(item for item in value if isinstance(item, dict))
    return ()



def _trade(
    record: source_index.SourceRecord,
    ctx: CaseContext,
    result: GraphActions,
    pack: str,
    once_caps: set[str],
) -> Action | None:
    """交易来源：报价里写了「给几件、要几个什么」。

    报价按职业/等级汇总在 `trade_offer` 里，玩家到村庄就能开界面，
    所以前置是一趟村庄（`capability:minecraft:villages`，`once`），
    跟箱子共用同一笔；要的绿宝石作为 `per_use` 前置，由别的来源定价。
    """
    subject = record.subject
    offers: list[dict] = []
    matched = ""
    for candidate in _trade_candidates(subject):
        found = _offers_for(ctx, candidate, record.item)
        if found:
            offers, matched = found, candidate
            break
    if not offers:
        result.uncovered[f"报价里没有该物品:{subject}"] += 1
        return None
    offer = max(offers, key=lambda item: item["gives"].get("count", 1))
    gives = offer["gives"]
    amount = float(gives.get("count", 1))
    # 对价有两处：`wants`（主槽位）与 `additional_wants`（第二槽位）。
    # 附魔书的报价就是「绿宝石 + 书」，只读 `wants` 会把书这项丢掉。
    entries = _want_entries(offer.get("wants")) + _want_entries(
        offer.get("additional_wants")
    )
    wants = [
        (entry["id"], float(entry["count"]))
        for entry in entries
        # 数量为 0 的对价是「卖货换绿宝石」那条路的残留（`gives` 记负需求，
        # 抵扣到 0 之后剩一行空需求）。`Requirement` 要求用量为正，
        # 不滤掉会在全库构建时直接抛 `ActionError`。
        if float(entry.get("count") or 0) > 0
    ]
    # 但**数量 0 也可能是价格没解出来**：附魔书那条报价上游给的是
    # `{"count": 0, "id": "minecraft:emerald"}`，真实价格由
    # `enchant_randomly` 的附魔决定（vanilla 是 5–64，随附魔等级浮动），
    # 数据里根本没有数值。这种情况不能当「免费」，也不能猜一个数，
    # 只能记账并让路线缺席。
    unpriced = sorted(
        {
            entry["id"]
            for entry in entries
            if not float(entry.get("count") or 0) > 0 and entry.get("id")
        }
    )
    if not wants:
        result.uncovered[
            f"报价无对价:{subject}" + (f"（缺数量：{'、'.join(unpriced)}）" if unpriced else "")
        ] += 1
        return None
    if unpriced:
        # 有对价解不出数量（附魔书的绿宝石就是这种）：只算另一半会给出
        # 「一本书换一本附魔书」的错价，比缺席更糟。记账并让路线缺席。
        result.uncovered[f"报价对价不完整:{subject}:{'、'.join(unpriced)}"] += 1
        return None
    profession = matched.split(":")[-1].split("/")[0]
    level = _trade_level(matched)
    if profession == WANDERING_TRADER:
        # 流浪商人不是结构，没有「去哪找」的间距可查——他是随机遭遇。
        # 前置故意不造来源动作，路线会被引擎判为不可达（并可在 `skipped` 里看到），
        # 而不是被伪装成「去趟村庄就有」。数据接上了，缺的是「遭遇频率」建模。
        cap = WANDERING_TRADER_CAP
        where = "流浪商人"
    else:
        cap = _ensure_capability(
            ctx, result, once_caps, "minecraft:villages", route="surface"
        )
        where = f"村庄的 {_short(subject)}"
    requires = [Requirement(name, qty, MODE_PER_USE) for name, qty in wants]
    if cap:
        requires.append(Requirement(cap, 1.0, MODE_ONCE))
    detail = "、".join(f"{qty:g}×{_short(name)}" for name, qty in wants)
    if level > 1:
        # 等级门槛单独造一条动作（见 `_villager_level_capability()`），
        # 挂在 `once` 上：升到 4 级只付一次，买第 2、3 个末影珍珠不再重付。
        # 不能并进 `per_use` —— 那等于每买一件都重新养一遍村民。
        trained = _villager_level_capability(
            ctx, result, once_caps, profession, level
        )
        if trained:
            requires.append(Requirement(trained, 1.0, MODE_ONCE))
            detail = f"{detail}（需村民 {level} 级）"
    return Action(
        action_id=f"trade:{_short(subject)}:{_short(record.item)}:{_short(offer.get('trade') or '')}",
        item=record.item,
        cost=seconds(gamedata.TRADE_SECONDS),
        yields={record.item: amount},
        requires=tuple(requires),
        label=f"跟{where}换：{detail} → {amount:g} 个",
        source=f"trade_offer:{subject}",
    )



# 村民升级需要的交易次数。Minecraft 的经验机制很难离线算，这里不做经验建模，
# 只保留一个可核对的上界：**每级只交易一次就升下一级**。
# 实际 1→2 级要 2 次交易，所以这是**下界**（偏乐观），真实代价只会更高。
TRADES_PER_LEVEL = 1



def _trade_level(subject: str) -> int:
    """`minecraft:cleric/4` → 4；取不到就返回 1（视为无前置）。"""
    _, _, rest = subject.partition(":")
    _, sep, level = rest.partition("/")
    if not sep:
        return 1
    try:
        return max(1, int(level))
    except ValueError:
        return 1



def _all_offers_for(ctx: CaseContext, subject: str) -> list[dict]:
    """某职业/等级的全部报价（不限物品）。"""
    for row in ctx.store.rows.values():
        if row.stat_type != "trade_offer" or row.subject != subject:
            continue
        return [entry for entry in (row.value.get("offers") or ()) if isinstance(entry, dict)]
    return []



def _lightest_offer(offers: list[dict]) -> dict | None:
    """该级里用来「升级」的那一条报价：优先绿宝石对价，其次对价件数。

    只在**没有经验数据**时用作兜底。有 `xp` 时走 `_level_trades()`。

    不单纯按件数挑是因为不同对价的量级差很远：牧师 3 级既能「4 个绿宝石换萤石」
    也能「2 个兔子脚换绿宝石」，按件数会挑兔子脚（2 件 < 4 件），而兔子脚
    在模型里 16 TU 一个、绿宝石只要 3 TU——件数少不等于便宜。
    """
    usable = [offer for offer in offers if offer.get("wants")]
    if not usable:
        return None

    def rank(offer: dict) -> tuple[int, float]:
        wants = offer.get("wants") or ()
        emerald_only = all(entry.get("id") == "minecraft:emerald" for entry in wants)
        return (0 if emerald_only else 1, sum(float(e.get("count", 1)) for e in wants))

    return min(usable, key=rank)



def _xp_at(level: int) -> float:
    """村民到 `level` 级所需的**累计**经验。"""
    table = gamedata.VILLAGER_LEVEL_XP
    if level < 0:
        return 0.0
    return table[level] if level < len(table) else table[-1]



def _climb_rank(offer: dict) -> tuple[int, float, float]:
    """升级用哪条报价：先看能不能用绿宝石付，再看每次给多少经验，最后看对价件数。

    先按「每次经验多」排是为了少交易几次；同经验时才比件数。
    「绿宝石优先」的理由同 `_lightest_offer()`：它在模型里来源稳定、单价低，
    而「拿兔子脚换绿宝石」这类报价的对价常常比绿宝石本身还贵。
    """
    wants = offer.get("wants") or ()
    emerald_only = all(entry.get("id") == "minecraft:emerald" for entry in wants)
    return (
        0 if emerald_only else 1,
        -float(offer.get("xp") or 0.0),
        sum(float(entry.get("count", 1)) for entry in wants),
    )



def _level_trades(
    offers: list[dict], delta_xp: float
) -> tuple[list[tuple[dict, int]], float]:
    """凑够 `delta_xp` 要成交哪几次：`([(报价, 次数)], 还差多少经验)`。

    每条报价有交易次数上限（`max_uses`，通常 12 或 16），刷满了就得换下一条。
    按 `_climb_rank()` 的顺序贪心吃满，直到攒够经验或报价用尽。

    还剩经验（第二项 > 0）说明这一级靠现有报价升不上去，调用方要记成缺口。
    """
    ranked = [
        offer
        for offer in offers
        if isinstance(offer.get("xp"), (int, float))
        and float(offer["xp"]) > 0
        and offer.get("wants")
    ]
    ranked.sort(key=_climb_rank)
    out: list[tuple[dict, int]] = []
    remaining = delta_xp
    for offer in ranked:
        if remaining <= 1e-9:
            break
        per = float(offer["xp"])
        need = int(math.ceil(remaining / per - 1e-9))
        cap = offer.get("max_uses")
        cap = int(cap) if isinstance(cap, (int, float)) and cap > 0 else need
        trades = min(need, cap)
        if trades <= 0:
            continue
        out.append((offer, trades))
        remaining -= trades * per
    return out, max(0.0, remaining)



def _level_climb(
    ctx: CaseContext,
    result: GraphActions,
    profession: str,
    level: int,
    item: str,
) -> tuple[dict[str, float], str] | None:
    """升到 `level` 级要付的对价：`({物品: 数量}, 人读说明)`。

    **已由 `_villager_level_capability()` 取代**，保留给需要「一次性总账」的调用方。

    交易**按等级解锁**，所以要一级一级攒经验：每级反复用**该级**的报价成交，
    攒够 `VILLAGER_LEVEL_XP` 的档差就升一级。每次成交给多少经验由数据给
    （`trade_offer` 的 `offer["xp"]`），交易次数受 `max_uses` 限制。
    """
    if level <= 1:
        return None
    totals: dict[str, float] = {}
    parts: list[str] = []
    for prev in range(1, level):
        delta = _xp_at(prev + 1) - _xp_at(prev)
        offers = _all_offers_for(ctx, f"minecraft:{profession}/{prev}")
        plan, short = _level_trades(offers, delta)
        if not plan:
            # 没有经验数据：退回「交易一次就升级」的旧口径。
            pick = _lightest_offer(offers)
            plan = [(pick, TRADES_PER_LEVEL)] if pick is not None else []
        elif short > 1e-9:
            result.uncovered[
                f"村民升 {prev}→{prev + 1} 级还差 {short:g} 经验（报价次数上限不够）"
            ] += 1
        for offer, trades in plan:
            for entry in offer.get("wants") or ():
                name = entry.get("id")
                if not isinstance(name, str) or name == item:
                    continue
                qty = float(entry.get("count", 1)) * trades
                # 同一件东西在多个等级都要时合并，否则会被算成两次采购。
                totals[name] = totals.get(name, 0.0) + qty
                parts.append(f"{qty:g}×{_short(name)}")
    if not totals:
        return None
    return totals, " + ".join(parts)



def _villager_level_capability(
    ctx: CaseContext,
    result: GraphActions,
    once_caps: set[str],
    profession: str,
    level: int,
) -> str | None:
    """造「村民已升到 `level` 级」的 `once` 前置（已造过就复用）。

    为什么不把升级对价直接挂到交易动作上：那会把升级费并进 `per_use`，
    买第 2、3 件时又付一遍整段升级成本。等级是一次性的，必须走 `once`；
    而 `once` 前置不能和购买对价共用同一个物品名（引擎不允许同物品多模式），
    所以用一个只表示「等级到了」的构造产出来承接。

    **每一级为每条报价各造一条升级动作**，产出同一个能力。这样「花绿宝石买」
    与「卖货换绿宝石」都由引擎比价，而不是构建时拍一条——卖货那条会用
    报价里给的绿宝石**抵扣**本级的开销（`gives` 是绿宝石时记负额），
    不建模的话绿宝石需求会被高估一大截。
    """
    target = f"capability:villager:{profession}/{level}"
    if level <= 1:
        return None
    for prev in range(1, level):
        need = f"capability:villager:{profession}/{prev + 1}"
        if need in once_caps:
            continue
        delta = _xp_at(prev + 1) - _xp_at(prev)
        previous = _villager_level_capability(ctx, result, once_caps, profession, prev)
        offers = _all_offers_for(ctx, f"minecraft:{profession}/{prev}")
        made = _emit_training_actions(ctx, result, prev, delta, offers, need, previous)
        if not made:
            # 没有任何可用报价：能力造不出来，路线应当因不可达被标出。
            result.uncovered[f"缺升到 {prev + 1} 级的交易报价:{profession}"] += 1
            return None
        once_caps.add(need)
    return target if target in once_caps else None



def _emit_training_actions(
    ctx: CaseContext,
    result: GraphActions,
    prev: int,
    delta_xp: float,
    offers: list[dict],
    capability: str,
    previous: str | None,
) -> int:
    """为「升到 `prev + 1` 级」按每条报价造一条动作，返回造了几条。

    一条报价刷不完档差时（`max_uses` 不够），把剩下部分交给下一条报价，
    使每条动作都是「完整升一级」的独立方案，引擎直接比总价。

    `gives` 是绿宝石的报价（卖货）记**负**需求：卖出去换来的绿宝石正好
    抵扣这一级的开销。净额为负（赚了）就丢掉——模型不支持负成本，
    多出来的绿宝石算作另外的来源，不计入这里。
    """
    usable = [
        offer
        for offer in offers
        if isinstance(offer.get("xp"), (int, float))
        and float(offer["xp"]) > 0
        and offer.get("wants")
    ]
    used = 0
    for offer in usable:
        per = float(offer["xp"])
        need = int(math.ceil(delta_xp / per - 1e-9))
        cap = offer.get("max_uses")
        cap = int(cap) if isinstance(cap, (int, float)) and cap > 0 else need
        trades = min(need, cap)
        if trades <= 0:
            continue
        if trades * per < delta_xp - 1e-9:
            continue  # 这条报价刷满也不够升一级，跳过；由别的报价承担
        totals: dict[str, float] = {}
        parts: list[str] = []
        for entry in offer.get("wants") or ():
            name = entry.get("id")
            if not isinstance(name, str):
                continue
            qty = float(entry.get("count", 1)) * trades
            totals[name] = totals.get(name, 0.0) + qty
            parts.append(f"{qty:g}×{_short(name)}")
        gives = offer.get("gives") or {}
        if gives.get("id") == "minecraft:emerald":
            earned = float(gives.get("count", 1)) * trades
            totals["minecraft:emerald"] = totals.get("minecraft:emerald", 0.0) - earned
            parts.append(f"卖出得 {earned:g}×绿宝石")
        requires = [
            Requirement(name, qty, MODE_ONCE)
            for name, qty in totals.items()
            if qty > 1e-9
        ]
        if previous:
            requires.append(Requirement(previous, 1.0, MODE_ONCE))
        trade_id = offer.get("trade") or f"{prev}"
        result.emit(
            Action(
                action_id=f"train:{prev + 1}:{_short(trade_id)}",
                item=capability,
                cost=seconds(gamedata.TRADE_SECONDS),
                yields={capability: 1.0},
                requires=tuple(requires),
                label=(
                    f"把村民养到 {prev + 1} 级：{prev} 级成交 {trades} 次"
                    f"（每次 {per:g} 经验，需 {delta_xp:g}）"
                    + (f"；{' + '.join(parts)}" if parts else "")
                ),
                source="trade_offer:level_xp",
            )
        )
        used += 1
    return used



# `minecraft:smith` 不是独立职业，而是 toolsmith / weaponsmith 的公共报价集——
# 上游按注册表路径把 `villager_trade/smith/1/coal_emerald.json` 记成 `smith/1`，
# 而 `trade_offer` 里只有 `toolsmith/1` 与 `weaponsmith/1`（内容一致）。
# 不展开就永远匹配不到，会被误记成「报价里没有该物品」。
TRADE_ALIASES: dict[str, tuple[str, ...]] = {
    "smith": ("toolsmith", "weaponsmith"),
}



def _trade_candidates(subject: str) -> list[str]:
    """一个报价 subject 的全部可能写法，按优先级排列。

    上游有的写 `cleric/1`，有的写 `minecraft:cleric/1`；别名职业要展开成真实职业。
    """
    base: list[str] = [subject]
    if not subject.startswith("minecraft:"):
        base.insert(0, f"minecraft:{subject}")
    out: list[str] = []
    for name in base:
        namespace, _, rest = name.partition(":")
        profession, sep, level = rest.partition("/")
        alias = TRADE_ALIASES.get(profession)
        if alias and sep:
            out.extend(f"{namespace}:{real}/{level}" for real in alias)
        out.append(name)
    return list(dict.fromkeys(out))



def _offers_for(ctx: CaseContext, subject: str, item: str) -> list[dict]:
    """某职业/等级里所有「给这个物品」的报价。"""
    for row in ctx.store.rows.values():
        if row.stat_type != "trade_offer" or row.subject != subject:
            continue
        offers = row.value.get("offers") or ()
        return [
            entry
            for entry in offers
            if isinstance(entry, dict) and entry.get("gives", {}).get("id") == item
        ]
    return []
