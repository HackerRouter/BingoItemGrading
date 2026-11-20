"""来源 → 行动路线。

路线是槽位生成器的输入，不是难度本身。判定只用前置与来源对象：
不猜玩家会不会去地下，只看这条来源在结构上属于哪一层。
"""

from __future__ import annotations

from .constants import OTHER_DIMENSION_WORLDS, ROUTES
from .exposure import ExposureRoutes
from .knowledge import RouteRules


def decide(
    *,
    source_type: str,
    subject: str,
    prereq: tuple[str, ...],
    rules: RouteRules,
    structure_set: str | None = None,
    block_sets: tuple[str, ...] = (),
    structure_only: bool = False,
    exposure: ExposureRoutes | None = None,
) -> str:
    """给出行动路线。

    ## 判定顺序

    1. 维度关键词或前置含非主世界世界节点 → `other_dimension`
    2. **前置里的结构属于非主世界维度** → `other_dimension`
    3. 来源对象命中地下方块集 → `underground`
    4. 结构集合属于地下集合 → `underground`
    5. **方块只由结构模板放置（无世界生成特性）** → 按模板所属结构判定
    6. 其余 → `surface`

    第 2 条比关键词可靠：结构有明确的维度归属，而实体名不一定看得出维度。
    例：潜影贝来自末地城（`structure:minecraft:end_city`），但 `shulker` 这个名字
    看不出末地；它以前靠关键词兼底，关键词一漏就被当成主世界地表来源。

    `block_sets` 是该方块模板所属的结构集合；`structure_only` 表示它没有
    任何世界生成特性。两者都由 `placement.PlacementIndex` 给出。

    `branch_mine` 不在这里产生：它是玩家在拿到工具后主动开展的挖掘策略，
    只能由策略注册表声明。
    """
    if rules.other_dimension_of(subject) is not None:
        return "other_dimension"
    if OTHER_DIMENSION_WORLDS & set(prereq):
        return "other_dimension"
    if rules.dimension_of_structures(prereq) is not None:
        return "other_dimension"

    if source_type in ("block_drop", "shear", "suspicious_block"):
        # **实测暴露优先**：`routes.toml` 的地下清单是手写的（只有 5 个矿石 +
        # 4 个前缀），`iron_ore` 根本不在里面，会被当成地表。有 exposure 数据时
        # 改用「多数方块贴空气或水 → 地表」。
        if exposure is not None:
            measured = exposure.route_for(subject)
            if measured is not None:
                return measured
        if rules.is_underground_block(subject):
            return "underground"

    if structure_set is not None and structure_set in rules.underground_structure_sets:
        return "underground"

    if source_type in ("loot_table", "suspicious_block"):
        if rules.is_underground_structure(subject):
            return "underground"

    # 只由结构放置的方块：它的路线就是那个结构的路线。
    if source_type == "block_drop" and structure_only:
        if set(block_sets) & set(rules.underground_structure_sets):
            return "underground"
        # 结构本身在主世界、末地或下界。末地/下界由结构集合名判不出，
        # 但这类方块数量少且多为装饰，先按地表处理并留待诊断暴露。

    return "surface"
