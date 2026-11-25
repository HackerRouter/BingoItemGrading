"""路线图的外层 HTML 与落盘。

复用 RA 的 `build_dot` 生成图，但保留本项目的「路线对照表」——RA 的
`render_html` 统计的是折叠数、假设数这些本仓库没有的指标。图注解释
item / rule 两种节点与红色高亮的含义。
"""

from __future__ import annotations

import html
from pathlib import Path

from ..plan.explain import PathTree
from .adapter import to_path_graph
from .colors import cost_cap, route_color, route_ink
from .options import PathOptions
from .render import build_dot, dot_to_svg


def _frontier_table(frontiers: list[dict]) -> str:
    """「换个前置来源要贵多少」。空表不占位。"""
    if not frontiers:
        return ""
    rows = "".join(
        f'<tr><td>{html.escape(row["item"].split(":", 1)[-1])}</td>'
        f'<td>{html.escape(row["action"])}</td>'
        f'<td>{html.escape(row["alternative"] or "（无替代来源）")}</td>'
        f'<td>{row["route_total"]:.2f} TU</td>'
        f'<td>+{row["delta"]:.2f}（+{row["delta_ratio"] * 100:.1f}%）</td></tr>'
        for row in frontiers
    )
    return f"""
<h2>前置替换成本</h2>
<div class="sub">
  口径：禁用该前置当前的来源后<b>重新求解整条路线</b>，差额含固定成本去重与多级依赖的
  真实变化，不是各层单价相加。「换成什么」是求解器在缺这个来源时的最优选择。
</div>
<table><thead><tr><th>前置</th><th>当前来源</th><th>换成什么</th><th>整条路线</th>
<th>差额</th></tr></thead><tbody>{rows}</tbody></table>
"""


def render_html(
    svg_text: str,
    trees: list[PathTree],
    target: str,
    *,
    frontiers: list[dict] | None = None,
) -> str:
    """自包含 HTML：内嵌 SVG + 路线对照表 +（可选）前置替换成本表。"""
    best = min((tree.total_cost for tree in trees if tree.total_cost > 0), default=0.0)
    cap = cost_cap(trees, best)
    rows = []
    for index, tree in enumerate(sorted(trees, key=lambda item: item.rank)):
        ratio = tree.total_cost / best if best > 0 else 1.0
        # 并列最优只给第一条红色锚点，其余同价路线见对照表。
        chip = route_ink(ratio, cap) if index == 0 else route_color(ratio, cap)
        rows.append(
            f'<tr><td>#{tree.rank}</td>'
            f'<td><span class="chip" style="background:{chip}"></span>{ratio:.3f}×</td>'
            f"<td>{tree.unit_cost:.2f} TU</td>"
            f"<td>{tree.total_cost:.2f} TU</td>"
            f"<td>{tree.rank_gap:+.2f}</td>"
            f"<td>{'(最优)' if tree.rank == 1 else ''}</td></tr>"
        )
    body = "".join(rows)
    if cap > 1.0:
        ramp_note = (
            f"其余来源按与最优的成本比由浓到浅：本图最差分支（{cap:.3f}×）"
            "用最浅色。"
        )
    else:
        ramp_note = "所有路线同价。"
    name = html.escape(target.split(":", 1)[-1])
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>合成图 · {name}</title>
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
<h1>合成图 · {name}</h1>
<div class="sub">
  箭头指「来源 → 产物」，从上往下读是一条获取路径，产物沉在整张图最下面。
  <b>椭圆 = 物品</b>：多条入边就是同一物品的多个候选来源（OR），最优那条在红色路线上；
  <b>圆角矩形 = 一条动作</b>：多条入边是它的并列前置（AND），缺一不可。
  <b>红色 = 最优的那条路线</b>（从原料一路走到 target）。只有一个候选来源时它同样标红
  —— 那就是唯一的路；并列最优只在图上标红第一条，其余同价路线见下方对照表，名次会并列。
  每个动作节点的数字写成一条等式：<b>`单价 × 需要量 + 固定 = 整次`</b>。
  `单价` 已含直接前置的边际（`×1/9` 表示一次动作产出 9 件、这里只分摊九分之一），
  `固定` 是这一段的固定成本（去村庄、进下界、打一场龙这类只付一次的开销），`整次` 就是凑够这件东西的
  总价 —— 根节点那个数等于 target 边上标的数字。
  固定成本按名字去重，同一条路线里只算一次，所以<b>子节点各自相加可能大于父节点</b>：
  共享的那笔在两处都会展示，但只收一次。
  <b>把鼠标放到节点上</b>可以看到单价由哪几项折进来、以及哪些固定成本被合并掉了。
  橙框虚线节点 = 还有若干条候选没画（贵过阈值或超出节点上限，tooltip 里写原因）。{ramp_note}
  虚线框是展到深度上限的节点——它的成本已经算进去了，省掉的只是更下游的明细。
  虚线<b>回边</b>是「这一步要用的东西本页已经在造了」：例如用钻石块分解出钻石，而钻石块
  又要钻石合成，箭头会绕回上面的物品节点，那一份按该物品的最优价计。
</div>
<div class="card">{svg_text}</div>
<h2>路线对照</h2>
<table><thead><tr><th>名次</th><th>成本比</th><th>单价</th><th>整次</th>
<th>比最优</th><th></th></tr></thead><tbody>{body}</tbody></table>
{_frontier_table(frontiers or [])}
</body></html>
"""


def write_outputs(
    base: Path,
    trees: list[PathTree],
    target: str,
    *,
    rankdir: str = "TB",
    frontiers: list[dict] | None = None,
    solved=None,
    actionset=None,
    branches: int = 0,
    max_nodes: int = 0,
    ratio_limit: float = 0.0,
) -> list[str]:
    """写 `<base>.dot`，能画 SVG 时再写 `<base>.svg` 与 `<base>.html`。

    默认 `rankdir=TB`：来源在上、产物沉到最下面，读图顺序与施工顺序一致。
    """
    if not trees:
        return []
    stem = base.with_suffix("") if base.suffix else base
    if stem.parent and not stem.parent.exists():
        stem.parent.mkdir(parents=True, exist_ok=True)
    graph = to_path_graph(
        trees,
        target,
        rankdir=rankdir,
        solved=solved,
        actionset=actionset,
        branches=branches,
        max_nodes=max_nodes,
        ratio_limit=ratio_limit,
    )
    dot_text = build_dot(graph, PathOptions(rankdir=rankdir))
    dot_path = stem.with_suffix(".dot")
    dot_path.write_text(dot_text, encoding="utf-8", newline="\n")
    written = [str(dot_path)]
    svg = dot_to_svg(dot_text)
    if svg is not None:
        svg_path = stem.with_suffix(".svg")
        svg_path.write_text(svg, encoding="utf-8", newline="\n")
        written.append(str(svg_path))
        svg_text = svg[svg.find("<svg"):] if "<svg" in svg else svg
    else:
        svg_text = (
            '<p class="warn">没有找到 <code>dot</code>，无法生成 SVG。'
            "DOT 文件已写出，装好 Graphviz 后重新生成即可。</p>"
        )
    html_path = stem.with_suffix(".html")
    html_path.write_text(
        render_html(svg_text, trees, target, frontiers=frontiers),
        encoding="utf-8",
    )
    written.append(str(html_path))
    return written
