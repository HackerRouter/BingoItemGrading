"""交易：一条报价一个动作，选哪条交给引擎。"""

from __future__ import annotations


from bingo_grading import gamedata
from bingo_grading.case.context import CaseContext, Sourced
from bingo_grading.plan import Action, Requirement
from bingo_grading.plan.actions import MODE_PER_USE
from .bundle import ActionBundle, seconds




# ---------------------------------------------------------------- 交易


def trade_offers(
    bundle: ActionBundle,
    ctx: CaseContext,
    *,
    profession: str,
    level: int | str,
    prefix: str | None = None,
) -> list[Action]:
    """某职业某等级的全部报价 → 每条报价一个动作。

    「四条等价交易选哪条」不需要人定：它们就是四条来源，
    引擎按「每个绿宝石的成本」排序后自己选。
    """
    found = ctx.trade_offers(profession, level)
    if found is None:
        bundle.note(f"缺 {profession}/{level} 的报价，这条路线缺席")
        return []
    offers, detail = found
    prefix = prefix or f"trade:{profession}/{level}"
    out: list[Action] = []
    for index, offer in enumerate(offers):
        # 上游的报价是「一对多进、一个出」：`wants` 是条目列表，
        # `gives` 是单个条目 `{"id": ..., "count": ...}`。
        gives = offer.get("gives") or {}
        wants = offer.get("wants") or ()
        given = gives.get("id")
        given_count = float(gives.get("count") or 0.0)
        if not given or given_count <= 0 or not wants:
            continue
        max_uses = offer.get("max_uses")
        if not isinstance(max_uses, (int, float)) or max_uses <= 0:
            bundle.note(
                f"{profession}/{level} 报价 {index} 缺成交上限（max_uses），跳过该报价"
            )
            continue
        out.append(
            Action(
                action_id=f"{prefix}#{index}",
                item=given,
                cost=seconds(gamedata.TRADE_SECONDS),
                yields={given: given_count},
                capacity=float(max_uses),
                requires=tuple(
                    Requirement(
                        entry["id"], float(entry["count"]), MODE_PER_USE
                    )
                    for entry in wants
                    if entry.get("id") and entry.get("count")
                ),
                label=(
                    f"{profession}/{level} 报价 {index}："
                    + " + ".join(
                        f"{entry.get('count'):g}×{entry.get('id')}"
                        for entry in wants
                    )
                    + f" → {given_count:g}×{given}"
                ),
                source=f"trade_offer:{profession}/{level}",
            )
        )
    if out:
        bundle.record(prefix, Sourced(float(len(out)), "trade_offer", detail))
    return out
