"""紫水晶洞：找到一个洞采一窝，而不是按散点密度外推。

只有 `amethyst_cluster`（成熟簇）掉碎片，小/中/大芽挖掉什么都不给——
所以收益必须按「每洞几颗**成熟**簇」算，不能把芽也算进去。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from bingo_grading import grade
from bingo_grading import gamedata
from bingo_grading.case.context import CaseContext
from bingo_grading.plan import solve
from bingo_grading.sources import actions

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "stats" / "26.3"
INDEX = ROOT / "build" / "26.3" / "source_index.jsonl"

needs_data = pytest.mark.skipif(
    not SNAPSHOT.exists() or not INDEX.exists(),
    reason=f"缺少快照 {SNAPSHOT} 或来源索引 {INDEX}",
)


@pytest.fixture(scope="module")
def ctx() -> CaseContext:
    return CaseContext.load(SNAPSHOT)


@needs_data
def test_geode_harvest_uses_measured_densities(ctx: CaseContext) -> None:
    """每洞收益 = 成熟簇占比 × 每洞 budding 数 × 每簇碎片数，占比来自实测。"""
    got = ctx.geode_harvest()
    assert got is not None
    shards, detail = got
    assert 4.0 < shards.value < 7.0, detail
    # 这里原本锁死一个具体百分比（"4.27%"），但占比是**实测值**，样本一变大
    # 就会变（r=2050 → 4.27%，r=4096 → 4.42%）。锁定数字等于把测试绑在
    # 某次扫描范围上，范围一改就误报。真正该断言的是「占比确实来自实测，
    # 且落在能算出合理产量的区间」。
    m = re.search(r"成熟簇占比\s*([\d.]+)%", detail)
    assert m, f"明细里没有成熟簇占比：{detail}"
    share = float(m.group(1))
    assert 2.0 < share < 12.0, f"成熟簇占比 {share}% 超出合理区间，像是取错了分母"


def test_budding_per_geode_is_the_only_external_constant() -> None:
    """每洞 budding 数是唯一的结构常量，数据包调生成率不影响它。"""
    assert gamedata.GEODE_BUDDING > 0


@needs_data
def test_geode_route_beats_chest_looting(ctx: CaseContext) -> None:
    """挖洞采一窝应当远便宜于按散点模型算出的结果。"""
    built = actions.build(ctx, "minecraft:amethyst_shard")
    aset = built.actionset()
    solved = solve(aset, "minecraft:amethyst_shard", 1.0)
    cost, action_id, _ = grade.best_whole_cost(
        aset, solved.curves, "minecraft:amethyst_shard", 1.0
    )
    assert cost is not None
    assert action_id.startswith("mine:geode:"), f"实际走 {action_id}"
    # 散点模型的时代这里要 6360 TU；现在挖洞采一窝应当在几百秒量级
    assert cost < 420.0, cost


@needs_data
def test_geode_action_yields_only_mature_clusters(ctx: CaseContext) -> None:
    """收益按成熟簇算：不能把不掉碎片的小/中/大芽算进去。"""
    built = actions.build(ctx, "minecraft:amethyst_shard")
    action = next(
        a for a in built.bundle.actions if a.action_id.startswith("mine:geode:")
    )
    shards = action.yields["minecraft:amethyst_shard"]
    harvest = ctx.geode_harvest()
    assert harvest is not None
    assert shards == pytest.approx(harvest[0].value)
