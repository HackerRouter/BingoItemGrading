"""求解器：拓扑序 DP、环的处理、路径无关性。"""

from __future__ import annotations

import pytest

from bingo_grading.plan import Action, ActionSet, Requirement
from bingo_grading.plan.actions import MODE_PER_USE
from bingo_grading.plan.solve import _component_order, solve
from bingo_grading.sources import actionsets


def _chain() -> ActionSet:
    """c → b → a，无环。"""
    return ActionSet(
        label="chain",
        actions=(
            Action(
                action_id="loot:a",
                item="minecraft:a",
                cost=10.0,
                yields={"minecraft:a": 1.0},
            ),
            Action(
                action_id="craft:b",
                item="minecraft:b",
                cost=1.0,
                yields={"minecraft:b": 2.0},
                requires=(Requirement("minecraft:a", 1.0),),
            ),
            Action(
                action_id="craft:c",
                item="minecraft:c",
                cost=1.0,
                yields={"minecraft:c": 1.0},
                requires=(Requirement("minecraft:b", 1.0),),
            ),
        ),
    )


def _ring() -> ActionSet:
    """a ↔ b 的环，a 另有外部入口。

    `craft:b_from_a` 一次吃 9 个 a 出 1 个 b，`craft:a_from_b` 一次吃 1 个 b
    出 9 个 a。两条合起来是「块/物」关系，不允许凭空变便宜。
    """
    return ActionSet(
        label="ring",
        actions=(
            Action(
                action_id="loot:a",
                item="minecraft:a",
                cost=10.0,
                yields={"minecraft:a": 1.0},
            ),
            Action(
                action_id="craft:b_from_a",
                item="minecraft:b",
                cost=0.0,
                yields={"minecraft:b": 1.0},
                requires=(Requirement("minecraft:a", 9.0, MODE_PER_USE),),
            ),
            Action(
                action_id="craft:a_from_b",
                item="minecraft:a",
                cost=0.0,
                yields={"minecraft:a": 9.0},
                requires=(Requirement("minecraft:b", 1.0, MODE_PER_USE),),
            ),
        ),
    )


def test_dag_does_not_discount_inside_a_ring() -> None:
    """环内的「块 ↔ 物」往返不能把物品价格压到外部入口以下。"""
    actionset = _ring()
    dag = solve(actionset, "minecraft:a", 1.0)
    cost = dag.curve_of("minecraft:a").cost(1.0)
    # 入口价 10；往返路线要用 9 个 a 才换回 9 个 a，只会更贵。
    assert cost == pytest.approx(10.0)
    assert dag.curve_of("minecraft:b").cost(1.0) > 0


def test_ring_with_entry_stays_reachable() -> None:
    """有外部入口的环不能被判成死锁：两条路都要能给出有限价格。"""
    actionset = _ring()
    dag = solve(actionset, "minecraft:b", 1.0)
    assert dag.curve_of("minecraft:a").cost(1.0) < float("inf")
    assert dag.curve_of("minecraft:b").cost(1.0) < float("inf")
    # 有入口的环不进 `cycles`（那只报「没有外部入口」的死锁），但两件物品
    # 都必须拿到依赖层号——拿不到就说明被当成不可达了。
    assert dag.schedule.tier_of("minecraft:a") is not None
    assert dag.schedule.tier_of("minecraft:b") is not None


def test_component_order_puts_dependencies_first() -> None:
    """缩点后的顺序必须让「前置所在的物品」先算。"""
    graph = {
        "minecraft:a": {"minecraft:b"},
        "minecraft:b": {"minecraft:c"},
        "minecraft:c": set(),
    }
    component, members, order = _component_order(graph)
    position = {cid: index for index, cid in enumerate(order)}
    assert position[component["minecraft:c"]] < position[component["minecraft:b"]]
    assert position[component["minecraft:b"]] < position[component["minecraft:a"]]
    assert sum(len(values) for values in members.values()) == 3


@pytest.mark.slow
@pytest.mark.skipif(
    not actionsets.default_path("26.3").exists(),
    reason="需要先跑 `bg index actions` 生成落盘动作图",
)
def test_dag_is_independent_of_graph_size() -> None:
    """真实图上：全图与单件子图给出同一个价格（分层会不一致）。

    这条是拓扑 DP 相对分层值迭代的实质差别：分层结果依赖「图里还有多少别的
    物品」（层数上限是全局的），而拓扑 DP 只依赖目标自己的依赖链。
    """
    graph = actionsets.read(actionsets.default_path("26.3"))
    whole = solve(graph.actionset, "minecraft:diamond", 1.0, prune_dominated=False)
    for name in ("minecraft:emerald", "minecraft:trident", "minecraft:diamond"):
        subset = graph.subgraph(name)
        small = solve(subset, name, 1.0, prune_dominated=False)
        assert small.curve_of(name).cost(1.0) == whole.curve_of(name).cost(1.0), name
