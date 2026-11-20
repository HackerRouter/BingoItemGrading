"""动作工厂：把 `CaseContext` 的取数算子包成引擎认识的 `Action`。

案例只声明「这件物品有哪些来源」，成本怎么算全在这里。这样有三条好处：

- 新增一个目标 = 拼一张动作表，不改任何计算；
- 改一个口径（比如箱子数换成实测）= 改一处，所有目标同步；
- 引擎的通用规则（供给曲线、容量、`once` 去重、`race` 并行、预算分层）
  自动对每个目标生效，不需要各写一遍。

**这里是唯一允许出现「成本公式」的地方。** 案例文件里不该再有 `travel + chest * n`
这样的算式——那意味着有人又开了第二条实现路径。

实现按来源类型拆成子模块；本文件只做门面。
"""

from __future__ import annotations

from .bundle import ActionBundle, capability, craft, need, seconds, smelt
from .exposure import mine_cave, mine_surface
from .loot import loot_site
from .mining import descend_cost, mine_geode, mine_vein
from .special import resin_farm
from .structure import structure_block
from .trade import trade_offers

__all__ = [
    "ActionBundle",
    "capability",
    "craft",
    "descend_cost",
    "loot_site",
    "mine_cave",
    "mine_geode",
    "mine_surface",
    "mine_vein",
    "need",
    "resin_farm",
    "seconds",
    "smelt",
    "structure_block",
    "trade_offers",
]
