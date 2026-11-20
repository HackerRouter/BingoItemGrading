"""特殊触发：需要游戏机制而非密度的来源（树脂）。"""

from __future__ import annotations

import math

from bingo_grading import gamedata
from bingo_grading.case.context import CaseContext
from bingo_grading.plan import Action
from .bundle import ActionBundle, seconds




def resin_farm(
    bundle: ActionBundle,
    ctx: CaseContext,
    *,
    item: str,
    action_id: str,
    per_trigger: float = gamedata.RESIN_PER_TRIGGER,
    cooldown_seconds: float = gamedata.RESIN_COOLDOWN_SECONDS,
    break_seconds: float = gamedata.RESIN_BREAK_SECONDS,
) -> Action | None:
    """打嘎枝换树脂：heart 在相连原木上长 2–3 块，5 秒冷却，挖走。

    嘎枝本身**不掉落任何东西**（`entities/creaking.json` 是空表，这不是数据
    缺口）；收益来自它能反复触发 heart 长树脂，所以这是一条可持续路线，
    不像「挖掉 heart」那样只有一锤子买卖。

    等待入夜不计成本，到达一处 heart 的代价是一次性的（`overhead`）：
    先跑到苍白之园，再在群系里找带心的树。
    """
    reach = ctx.pale_garden_heart_reach()
    if reach is None:
        return None
    found, detail = reach
    per_item = (
        cooldown_seconds + gamedata.RESIN_HIT_SECONDS + per_trigger * break_seconds
    ) / per_trigger
    action = Action(
        action_id=action_id,
        item=item,
        cost=seconds(per_item),
        yields={item: 1.0},
        capacity=math.inf,
        overhead=(("reach:pale_garden", found.value),),
        label=(
            f"夜里打一只被 creaking heart 护着的嘎枝，heart 在相连原木上长 "
            f"{per_trigger:g} 块树脂团（冷却 {cooldown_seconds:g}s），挖走；{detail}"
        ),
        source=f"{found.source}+wiki",
    )
    return action
