"""单节点观察：把某个物品在模型里的现状摊开。

`grade` 把一个物品压成一行（分数、整次成本、可信度），用来横向比较。
调模型时要看的是另一组问题：

- 这条价是从哪个动作来的，那个动作自己的单价与固定成本是多少；
- 它的每个前置各花了多少钱、付的是 `once` 还是 `per_use`；
- 曲线前几段还有哪些来源、差多少；
- 换一套求解器算同一个节点，差多少。

这里只做展示，不引入任何新的成本口径。
"""

from __future__ import annotations

import math

from bingo_grading import units
from bingo_grading.grade import _display_width
from bingo_grading.plan import SupplyError
from bingo_grading.plan.explain import MAX_DEPTH, _step, has_cycle


def _charge_dict(charge) -> dict:
    return {
        "item": charge.item,
        "qty": charge.qty,
        "mode": charge.mode,
        "cost_tu": None if not charge.finite else round(charge.cost, 4),
        "marginal_tu": None if not math.isfinite(charge.marginal) else round(charge.marginal, 4),
        "via": charge.via,
        "fixed": {
            name: round(amount, 4) for name, amount in charge.fixed_items
        },
    }


def _segment_hits(curves, action_id: str) -> list[dict]:
    """这个动作在哪些物品的曲线里露过面。

    曲线是「最终结果」——一个动作可能还留在曲线上但不是最便宜那段。看
    「它值多少、被谁盖住了」比只看最便宜段有用。
    """
    hits = []
    for item, curve in curves.items():
        for segment in curve.segments:
            if segment.action_id != action_id and not any(
                name == action_id for name, _ in segment.members
            ):
                continue
            hits.append(
                {
                    "item": item,
                    "unit_cost": round(segment.unit_cost, 4),
                    "fixed_cost": round(segment.fixed_cost, 4),
                    "capacity": None
                    if math.isinf(segment.capacity)
                    else round(segment.capacity, 4),
                    "level": segment.level,
                    "merged": bool(segment.members),
                }
            )
    return hits


def report_action(actionset, solved, action_id: str) -> dict:
    """一个动作的明细：自身代价、前置怎么付、它的产出去哪了。"""
    action = actionset.get(action_id)
    charges = solved.charges.get(action_id, ())
    once_total = sum(
        charge.cost for charge in charges if charge.mode == "once"
    )
    per_use_marginal = sum(
        charge.marginal for charge in charges if charge.mode == "per_use"
    )
    return {
        "action_id": action_id,
        "item": action.item,
        "cost_tu": round(action.cost, 4),
        "yields": {name: round(amount, 4) for name, amount in action.yields.items()},
        "capacity": None if math.isinf(action.capacity) else action.capacity,
        "race": action.race,
        "equivalents": {
            name: round(weight, 4) for name, weight in action.equivalents.items()
        },
        "overhead": [[name, round(amount, 4)] for name, amount in action.overhead],
        "per_invocation_tu": round(action.cost + per_use_marginal, 4),
        "once_total_tu": round(once_total, 4),
        "fixed_total_tu": round(action.overhead_total() + once_total, 4),
        "requires": [_charge_dict(charge) for charge in charges],
        "segments": _segment_hits(solved.curves, action_id),
        "label": action.label,
        "source": action.source,
    }


def _segment_dict(actionset, solved, segment, *, detail: bool) -> dict:
    out = {
        "action_id": segment.action_id,
        "unit_cost": round(segment.unit_cost, 4),
        "fixed_cost": round(segment.fixed_cost, 4),
        "capacity": None if math.isinf(segment.capacity) else round(segment.capacity, 4),
        "level": segment.level,
    }
    if segment.members:
        out["members"] = [
            {"action_id": action_id, "unit_cost": round(unit_cost, 4)}
            for action_id, unit_cost in segment.members
        ]
    if not detail:
        return out
    if segment.label:
        out["label"] = segment.label
    action = actionset.get(segment.action_id) if not segment.members else None
    if action is not None:
        out["action"] = {
            "cost": round(action.cost, 4),
            "yields": {name: round(amount, 4) for name, amount in action.yields.items()},
            "overhead": [[name, round(amount, 4)] for name, amount in action.overhead],
            "capacity": None if math.isinf(action.capacity) else action.capacity,
        }
    charges = solved.charges.get(segment.action_id)
    if charges:
        out["requires"] = [_charge_dict(charge) for charge in charges]
    return out


def price_table(solved, demand: float = 1.0) -> dict[str, float]:
    """全部可达物品的整次价格。取邻近价带用。"""
    table: dict[str, float] = {}
    for name in solved.curves:
        curve = solved.curve_of(name)
        try:
            value = curve.cost(demand)
        except SupplyError:
            continue
        if math.isfinite(value):
            table[name] = value
    return table


def neighbours(prices: dict[str, float], item: str, limit: int = 5) -> list[dict]:
    """价格最接近的几件物品（按相对差排序）。

    排除 `capability:`：那些是工具、站点、维度入口这类内部构造，把它们当
    「邻价参照」会把真正的可比物品挤掉。
    """
    own = prices.get(item)
    if own is None or limit <= 0:
        return []
    scored = []
    for name, value in prices.items():
        if name == item or name.startswith("capability:"):
            continue
        delta = abs(value - own)
        scored.append((delta / max(own, 1e-9), name, value))
    scored.sort()
    return [
        {
            "item": name,
            "cost_tu": round(value, 4),
            "delta_tu": round(value - own, 4),
            "ratio": round(ratio, 4),
        }
        for ratio, name, value in scored[:limit]
    ]


def _self_serving(actionset, solved, item: str, segments, demand: float) -> list[dict]:
    """哪些来源的成本里含「要先用它自己」的一份。

    钻石块 ↔ 钻石这类互逆配方：分解钻石块得到的钻石，成本里有一份是「先合成这个
    钻石块」，而合成它的钻石又得从这条路线上来。报价不是假的（锚定在外部的钻石价），
    但多绕一圈必然不合算，永远不该被选，所以单独列出来而不是混在候选里。
    """
    out = []
    for segment in segments:
        step = _step(
            actionset,
            solved,
            item,
            segment,
            demand,
            depth=MAX_DEPTH,
            stack=frozenset(),
            seen_once=set(),
        )
        if not has_cycle(step):
            continue
        out.append(
            {
                "action_id": segment.action_id,
                "unit_cost": round(segment.unit_cost, 4),
                "fixed_cost": round(segment.fixed_cost, 4),
                "label": segment.label,
            }
        )
    return out


def report_node(
    actionset,
    solved,
    item: str,
    *,
    demand: float = 1.0,
    neighbours_of: list[dict] | None = None,
) -> dict:
    """一个节点在模型里的现状。"""
    curve = solved.curve_of(item)
    try:
        total = curve.cost(demand)
    except SupplyError:
        total = math.inf
    feasible = bool(curve) and math.isfinite(total)
    head = curve.head
    node = {
        "item": item,
        "feasible": feasible,
        "cost_tu": None if not feasible else round(total, 4),
        "score": None if not feasible else units.score_from_cost(total),
        "tier": None if not feasible else units.tier_of(total),
        "demand": demand,
        "segments": len(curve.segments),
        "head": None if head is None else _segment_dict(actionset, solved, head, detail=True),
        "alternatives": [
            _segment_dict(actionset, solved, segment, detail=False)
            for segment in curve.segments[:3]
        ],
    }
    if neighbours_of is not None:
        node["neighbours"] = [dict(entry) for entry in neighbours_of]
    looping = _self_serving(actionset, solved, item, curve.segments, demand)
    if looping:
        node["self_serving"] = looping
    return node


def _cell(node: dict) -> list[str]:
    head = node["head"] or {}
    requires = head.get("requires") or []
    parts = []
    for charge in requires[:3]:
        name = charge["item"].split(":", 1)[-1]
        parts.append("%s×%g@%s" % (name, charge["qty"], charge["cost_tu"]))
    cells = [
        node["item"] if node["item"].startswith("capability:") else node["item"].split(":", 1)[-1],
        "inf" if node["cost_tu"] is None else "%.4f" % node["cost_tu"],
    ]
    cells.extend(
        [
            "%d" % node["segments"],
            head.get("action_id", ""),
            "" if not head else "%.4f" % head["unit_cost"],
            "" if not head else "%.4f" % head["fixed_cost"],
            "、".join(parts) if parts else "—",
        ]
    )
    return cells


def render(nodes: list[dict]) -> str:
    """对齐表格。中文按两列宽算（与 `grade.render_table` 同一套宽度规则）。"""
    header = ["节点", "整次 TU", "段", "最便宜来源", "单价", "固定", "前置（名称×件数@总价）"]
    body = [_cell(node) for node in nodes]
    widths = [
        max(_display_width(line[index]) for line in [header, *body])
        for index in range(len(header))
    ]

    def line_of(cells: list[str]) -> str:
        return "  ".join(
            cell + " " * (widths[index] - _display_width(cell))
            for index, cell in enumerate(cells)
        ).rstrip()

    lines = [line_of(header), "  ".join("-" * width for width in widths)]
    lines.extend(line_of(cells) for cells in body)
    if any(node.get("neighbours") for node in nodes):
        lines.append("")
        lines.append("## 邻近价带（相对差最小的几件）")
        lines.append("")
        for node in nodes:
            entries = node.get("neighbours") or []
            if not entries:
                continue
            title = "%s（%s TU）" % (
                node["item"],
                "inf" if node["cost_tu"] is None else "%.4f" % node["cost_tu"],
            )
            lines.append(title)
            header = ["物品", "TU", "差"]
            rows = []
            for entry in entries:
                rows.append(
                    [
                        entry["item"].split(":", 1)[-1],
                        "%.4f" % entry["cost_tu"],
                        "%+.4f" % entry["delta_tu"],
                    ]
                )
            inner = [
                max(_display_width(row[index]) for row in [header, *rows])
                for index in range(len(header))
            ]
            for row in [header, *rows]:
                lines.append(
                    "  "
                    + "  ".join(
                        cell + " " * (inner[index] - _display_width(cell))
                        for index, cell in enumerate(row)
                    ).rstrip()
                )
            lines.append("")
    looping = [node for node in nodes if node.get("self_serving")]
    if looping:
        lines.append("")
        lines.append("## 绕回自身的来源（成本含一份自我供给，永远不合算）")
        lines.append("")
        for node in looping:
            lines.append(node["item"])
            for entry in node["self_serving"]:
                lines.append(
                    "  %s  %.4f TU/个，固定 %.4f"
                    % (entry["action_id"], entry["unit_cost"], entry["fixed_cost"])
                )
    return "\n".join(lines).rstrip()


def render_actions(actions: list[dict]) -> str:
    """动作明细。物品表回答「多贵」，这里回答「这个动作怎么算出来的」。"""
    lines = ["## 动作明细", ""]
    for action in actions:
        lines.append("%s → %s" % (action["action_id"], action["item"]))
        yields = "、".join(
            "%s×%g" % (name, amount) for name, amount in action["yields"].items()
        )
        lines.append(
            "  cost %.4f TU/次；容量 %s；产出 %s"
            % (
                action["cost_tu"],
                "inf" if action["capacity"] is None else "%g" % action["capacity"],
                yields,
            )
        )
        lines.append(
            "  每次调用 %.4f（自身 %.4f + per_use 边际 %.4f）；一次性合计 %.4f"
            % (
                action["per_invocation_tu"],
                action["cost_tu"],
                action["per_invocation_tu"] - action["cost_tu"],
                action["fixed_total_tu"],
            )
        )
        requires = action["requires"]
        if requires:
            parts = []
            for charge in requires:
                parts.append(
                    "%s×%g 总价 %s（%s，边际 %s%s）"
                    % (
                        charge["item"],
                        charge["qty"],
                        "—" if charge["cost_tu"] is None else "%.4f" % charge["cost_tu"],
                        charge["mode"],
                        "—"
                        if charge["marginal_tu"] is None
                        else "%.4f" % charge["marginal_tu"],
                        "" if not charge["via"] else "，via " + charge["via"],
                    )
                )
            lines.append("  前置：" + "、".join(parts))
        else:
            lines.append("  前置：无")
        if action["overhead"]:
            lines.append(
                "  动作自身固定："
                + "、".join("%s %.4f" % (name, amount) for name, amount in action["overhead"])
            )
        if action["race"]:
            lines.append("  并行组：%s" % action["race"])
        if action["equivalents"]:
            lines.append(
                "  等价折算："
                + "、".join(
                    "%s×%g" % (name, weight)
                    for name, weight in action["equivalents"].items()
                )
            )
        hits = action["segments"]
        for hit in hits[:6]:
            lines.append(
                "  曲线：%s 单价 %.4f / 固定 %.4f / 容量 %s%s"
                % (
                    hit["item"],
                    hit["unit_cost"],
                    hit["fixed_cost"],
                    "inf" if hit["capacity"] is None else "%g" % hit["capacity"],
                    "（并行合成段）" if hit["merged"] else "",
                )
            )
        if len(hits) > 6:
            lines.append("  曲线：…共 %d 处" % len(hits))
        if not hits:
            lines.append("  曲线：没有进入任何物品的曲线（来源被更便宜的盖住或已不可达）")
        if action["label"]:
            lines.append("  说明：%s" % action["label"])
        lines.append("")
    return "\n".join(lines).rstrip()
