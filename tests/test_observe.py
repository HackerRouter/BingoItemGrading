"""单节点观察：邻近价带的选择与表格渲染。"""

from __future__ import annotations

from bingo_grading import observe


def test_neighbours_sorts_by_relative_difference() -> None:
    prices = {
        "minecraft:a": 10.0,
        "minecraft:b": 10.5,
        "minecraft:c": 9.0,
        "minecraft:d": 100.0,
        "capability:village": 10.1,
    }
    rows = observe.neighbours(prices, "minecraft:a", limit=2)
    assert [row["item"] for row in rows] == ["minecraft:b", "minecraft:c"]
    assert rows[0]["delta_tu"] == 0.5
    # 假物品（工具、站点）不参与邻价参照。
    assert all(not row["item"].startswith("capability:") for row in rows)


def test_neighbours_respects_limit_and_missing_item() -> None:
    prices = {"minecraft:a": 1.0, "minecraft:b": 1.2}
    assert len(observe.neighbours(prices, "minecraft:a", limit=0)) == 0
    assert observe.neighbours(prices, "minecraft:absent") == []


def test_render_includes_neighbour_section() -> None:
    nodes = [
        {
            "item": "minecraft:a",
            "cost_tu": 10.0,
            "segments": 2,
            "head": {
                "action_id": "craft:a",
                "unit_cost": 10.0,
                "fixed_cost": 0.0,
                "requires": [
                    {
                        "item": "minecraft:b",
                        "qty": 2.0,
                        "cost_tu": 9.0,
                    }
                ],
            },
            "neighbours": [
                {
                    "item": "minecraft:c",
                    "cost_tu": 10.5,
                    "delta_tu": 0.5,
                    "ratio": 0.05,
                }
            ],
        }
    ]
    text = observe.render(nodes)
    assert "craft:a" in text
    assert "邻近价带" in text
    assert "b×2@9.0" in text
    assert "c" in text


class _FakeSolved:
    """只提供 `report_action` 用到的两个字段。"""

    def __init__(self) -> None:
        self.charges = {"craft:a": ()}
        self.curves = {}


def test_report_action_reads_action_fields() -> None:
    """清单里给动作 id 时，报的是动作本身而不是「某物品的价」。"""
    from bingo_grading.plan import Action, ActionSet, Requirement

    actionset = ActionSet(
        label="probe",
        actions=(
            Action(
                action_id="craft:a",
                item="minecraft:a",
                cost=2.0,
                yields={"minecraft:a": 2.0},
                requires=(Requirement("minecraft:b", 3.0),),
                overhead=(("reach:overworld:y16", 1.5),),
                label="两个 b 换两个 a",
            ),
        ),
    )
    report = observe.report_action(actionset, _FakeSolved(), "craft:a")
    assert report["action_id"] == "craft:a"
    assert report["cost_tu"] == 2.0
    assert report["yields"] == {"minecraft:a": 2.0}
    assert report["per_invocation_tu"] == 2.0
    assert report["fixed_total_tu"] == 1.5
    assert report["overhead"] == [["reach:overworld:y16", 1.5]]
    assert report["segments"] == []
    text = observe.render_actions([report])
    assert "craft:a → minecraft:a" in text
    assert "没有进入任何物品的曲线" in text

