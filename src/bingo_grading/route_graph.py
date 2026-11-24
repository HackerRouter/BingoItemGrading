"""路线合成图：把 `rank_paths` 的路线树画成 DOT / SVG / HTML。

一条路线一棵树，**颜色浓度按「与最优路线的成本比」连续变化**：最优路线最深，
越贵越浅（`cost_ratio` 1 → 深色，≥4 → 最浅）。同一件物品的多条候选并排画，
一眼能看出哪条是主路、哪条只是备选。

Graphviz 是可选依赖：`dot` 不在 PATH 上时只写 `.dot`，由调用方决定是否报错。
"""

from __future__ import annotations

import html
import math
import subprocess
from pathlib import Path

from .plan.explain import PathTree, Step

# 成本比的着色端点。`CAP` 是「再贵也按最浅色画」的倍数。
BEST_COLOR = "#1d4e73"
WORST_COLOR = "#cbd8e3"
COST_RATIO_CAP = 4.0
TARGET_FILL = "#fef3c7"
TARGET_BORDER = "#b45309"
NOTE_FILL = "#fff7ed"
NOTE_BORDER = "#fb923c"


def graphviz_available() -> bool:
    """`dot` 在不在 PATH 上。和 RA 的做法一致：先单独判，缺了给明确提示。"""
    try:
        subprocess.run(["dot", "-V"], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def _mix(best: str, worst: str, t: float) -> str:
    """两个 `#rrggbb` 之间线性插值；`t=0` 取 best，`t=1` 取 worst。"""
    t = max(0.0, min(1.0, t))
    left = [int(best[index : index + 2], 16) for index in (1, 3, 5)]
    right = [int(worst[index : index + 2], 16) for index in (1, 3, 5)]
    mixed = [round(a + (b - a) * t) for a, b in zip(left, right)]
    return "#" + "".join(f"{value:02x}" for value in mixed)


def route_color(ratio: float) -> str:
    """成本比 → 颜色。1 倍（最优）最深，`COST_RATIO_CAP` 倍以上最浅。"""
    if ratio <= 1.0 or not math.isfinite(ratio):
        return BEST_COLOR
    t = math.log(ratio) / math.log(COST_RATIO_CAP)
    return _mix(BEST_COLOR, WORST_COLOR, t)


def _attr(text: str) -> str:
    """DOT 属性值转义。"""
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )


def _short(text: str, limit: int = 42) -> str:
    text = (text or "").strip()
    # 动作的 label 末尾常带「（minecraft:crafting_shaped；data/...json）」，
    # 图上留来源文件名没用，先切掉括号再截断。
    head = text.split("（", 1)[0].strip()
    if len(head) > limit:
        return head[: limit - 1] + "…"
    return head


def _node_label(step: Step) -> str:
    """节点标签：动作名 / 物品名 + 单价与需求量。"""
    if step.action_id:
        title = step.action_id.replace("minecraft:", "")
    else:
        title = step.item.split(":", 1)[-1]
    lines = [title]
    if step.label:
        lines.append(_short(step.label))
    if step.unit_cost and math.isfinite(step.unit_cost):
        lines.append(f"{step.unit_cost:.3f} TU/个 × {step.need:.3g}")
    if step.note:
        lines.append(step.note)
    return "\n".join(lines)


def _node_attrs(step: Step, color: str) -> str:
    """一个 `Step` 的 DOT 属性。"""
    attrs = {
        "label": f'"{_attr(_node_label(step))}"',
        "shape": "box",
        "style": '"filled,rounded"',
        "fillcolor": '"#f8fafc"',
        "color": f'"{color}"',
        "fontcolor": '"#22262a"',
        "fontsize": "10",
        "penwidth": "1.4",
        "margin": '"0.10,0.06"',
    }
    if step.note:
        # 环 / 深度截断：虚线橙框，和正常节点分开。
        attrs["style"] = '"dashed,filled"'
        attrs["fillcolor"] = f'"{NOTE_FILL}"'
        attrs["color"] = f'"{NOTE_BORDER}"'
        attrs["fontcolor"] = '"#9a3412"'
    return ", ".join(f"{key}={value}" for key, value in attrs.items())


def _step_key(step: Step) -> str:
    """同一动作（或同一前置物品）在多条路线里共用一个节点。

    有 `action_id` 时直接用它：动作 ID 已经是唯一的（同一动作服务多件物品时
    构建端会加 `@<物品>` 后缀），不必再拼 `step.item`——后者是**需求方**的物品，
    拼进去会让同一个采集动作按父物品重复画。共享节点能把「三条路线都要石镐」
    画成一条汇合的边。
    """
    if step.action_id:
        return step.action_id
    return f"need|{step.item}"


def build_dot(trees: list[PathTree], target: str, *, rankdir: str = "BT") -> str:
    """路线树 → DOT 文本。箭头指「前置 → 动作」，从下往上读是一条获取路径。

    节点跨路线共享：同一动作只画一次，颜色取它出现过的**最优先**路线；
    边也按 (前置, 动作) 去重，颜色取最优先的那条。
    """
    if not trees:
        return "digraph routes {\n}\n"
    best = min((tree.total_cost for tree in trees if tree.total_cost > 0), default=0.0)
    nodes: dict[str, tuple[Step, float]] = {}
    edges: list[tuple[str, str, float, str]] = []

    for tree in trees:
        ratio = tree.total_cost / best if best > 0 else 1.0

        def walk(step: Step, parent: str | None = None) -> None:
            key = _step_key(step)
            if key not in nodes or ratio < nodes[key][1]:
                nodes[key] = (step, ratio)
            if parent is None:
                edges.append(
                    (key, "target", ratio, f', label="{tree.total_cost:.1f} TU"')
                )
            else:
                edges.append((key, parent, ratio, _edge_label(step)))
            for child in step.children:
                walk(child, key)

        walk(tree.root)

    lines = [
        "digraph routes {",
        f"  rankdir={rankdir};",
        "  nodesep=0.18; ranksep=0.55;",
        "  bgcolor=white;",
        '  node [fontname="Microsoft YaHei", fontsize=10];',
        '  edge [fontname="Microsoft YaHei", fontsize=9, arrowsize=0.6];',
        f'  "target" [label="{_attr(target.split(":", 1)[-1])}", shape=ellipse,'
        f' style="filled", fillcolor="{TARGET_FILL}", color="{TARGET_BORDER}",'
        ' penwidth=2.4, peripheries=2, fontsize=12, fontcolor="#78350f"];',
    ]
    for key, (step, ratio) in nodes.items():
        color = route_color(ratio)
        lines.append(f'  "{key}" [{_node_attrs(step, color)}];')

    unique: dict[tuple[str, str], tuple[float, str]] = {}
    for source, destination, ratio, label in edges:
        pair = (source, destination)
        if pair not in unique or ratio < unique[pair][0]:
            unique[pair] = (ratio, label)
    for (source, destination), (ratio, label) in unique.items():
        color = route_color(ratio)
        penwidth = "2.0" if destination == "target" else "1.4"
        lines.append(
            f'  "{source}" -> "{destination}" [color="{color}",'
            f' penwidth="{penwidth}"{label}];'
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


def _edge_label(step: Step) -> str:
    """前置边上的数量标注。`once` 前置只写一次，不乘调用次数。"""
    if step.need and step.need != 1.0:
        return f', label="×{step.need:.3g}"'
    return ""


def render_html(dot_text: str, trees: list[PathTree], target: str) -> str:
    """自包含 HTML：内嵌 SVG，附每条路线的成本比与颜色说明。"""
    svg = _dot_to_svg(dot_text)
    if svg is None:
        svg = (
            '<p class="warn">没有找到 <code>dot</code>，无法生成 SVG。'
            "DOT 文件已写出，装好 Graphviz 后重新生成即可。</p>"
        )
    best = min((tree.total_cost for tree in trees if tree.total_cost > 0), default=0.0)
    rows = "".join(
        f'<tr><td>#{tree.rank}</td>'
        f'<td><span class="chip" style="background:'
        f'{route_color(tree.total_cost / best if best > 0 else 1.0)}"></span>'
        f'{(tree.total_cost / best if best > 0 else 1.0):.2f}×</td>'
        f"<td>{tree.unit_cost:.3f} TU/个</td>"
        f"<td>{tree.total_cost:.2f} TU</td>"
        f"<td>{tree.rank_gap:+.2f}</td>"
        f"<td>{'(最优)' if tree.rank == 1 else ''}</td></tr>"
        for tree in sorted(trees, key=lambda item: item.rank)
    )
    name = target.split(":", 1)[-1]
    safe_name = html.escape(name)
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>合成图 · {safe_name}</title>
<style>
:root {{ color-scheme: light dark; }}
body {{ margin: 0; padding: 28px 32px 48px; background: #fbfbfc; color: #22262a;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; }}
h1 {{ font-size: 19px; margin: 0 0 4px; }}
.sub {{ color: #8a9099; font-size: 13px; margin-bottom: 18px; line-height: 1.7; }}
.card {{ background: #fff; border: 1px solid #e6e8eb; border-radius: 10px;
  padding: 14px; box-shadow: 0 1px 2px rgba(16,24,40,.04); overflow: auto; }}
table {{ border-collapse: collapse; font-size: 13px; margin: 12px 0 4px; }}
th, td {{ text-align: left; padding: 5px 16px 5px 0; border-bottom: 1px solid #eef0f2; }}
th {{ color: #8a9099; font-weight: 600; }}
.chip {{ display: inline-block; width: 22px; height: 10px; border-radius: 3px;
  margin-right: 7px; vertical-align: 0; }}
.warn {{ background: #fff7ed; border: 1px solid #fdba74; color: #9a3412;
  padding: 10px 12px; border-radius: 8px; font-size: 13px; }}
h2 {{ font-size: 14px; margin: 22px 0 8px; }}
</style></head><body>
<h1>合成图 · {safe_name}</h1>
<div class="sub">
  箭头指「前置 → 动作」，从下往上读是一条获取路径。
  <b>颜色浓度 = 与最优路线的成本比</b>：最深是最优，越浅越贵（≥{COST_RATIO_CAP:g} 倍后到最浅）。
  虚线橙框 = 环或深度截断，不是正常来源。
</div>
<div class="card">{svg}</div>
<h2>路线对照</h2>
<table><thead><tr><th>名次</th><th>成本比</th><th>单价</th><th>整次</th>
<th>比最优</th><th></th></tr></thead><tbody>{rows}</tbody></table>
</body></html>
"""


def _dot_to_svg(dot_text: str) -> str | None:
    if not graphviz_available():
        return None
    try:
        result = subprocess.run(
            ["dot", "-Tsvg"],
            input=dot_text.encode("utf-8"),
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.decode("utf-8", errors="replace")


def write_outputs(base: Path, trees: list[PathTree], target: str) -> list[str]:
    """写 `<base>.dot`，能画 SVG 时再写 `<base>.svg` 与 `<base>.html`。"""
    stem = base.with_suffix("") if base.suffix else base
    if stem.parent and not stem.parent.exists():
        stem.parent.mkdir(parents=True, exist_ok=True)
    dot_text = build_dot(trees, target)
    dot_path = stem.with_suffix(".dot")
    dot_path.write_text(dot_text, encoding="utf-8", newline="\n")
    written = [str(dot_path)]
    svg = _dot_to_svg(dot_text)
    if svg is not None:
        svg_path = stem.with_suffix(".svg")
        svg_path.write_text(svg, encoding="utf-8", newline="\n")
        written.append(str(svg_path))
    html_path = stem.with_suffix(".html")
    html_path.write_text(render_html(dot_text, trees, target), encoding="utf-8")
    written.append(str(html_path))
    return written
