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


def render_html(
    svg_text: str, trees: list[PathTree], target: str
) -> str:
    """自包含 HTML：内嵌 SVG + 路线对照表。"""
    best = min((tree.total_cost for tree in trees if tree.total_cost > 0), default=0.0)
    cap = cost_cap(trees, best)
    rows = []
    for tree in sorted(trees, key=lambda item: item.rank):
        ratio = tree.total_cost / best if best > 0 else 1.0
        # 同价的两条路线里只有第一名带红色锚点。
        chip = route_ink(ratio, cap) if tree.rank == 1 else route_color(ratio, cap)
        rows.append(
            f'<tr><td>#{tree.rank}</td>'
            f'<td><span class="chip" style="background:{chip}"></span>{ratio:.2f}×</td>'
            f"<td>{tree.unit_cost:.2f} TU</td>"
            f"<td>{tree.total_cost:.2f} TU</td>"
            f"<td>{tree.rank_gap:+.2f}</td>"
            f"<td>{'(最优)' if tree.rank == 1 else ''}</td></tr>"
        )
    body = "".join(rows)
    if cap > 1.0:
        ramp_note = (
            f"其余来源按与最优的成本比由浓到浅：本图最差分支（{cap:.2f}×）"
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
  <b>椭圆 = 物品</b>：多条入边就是同一物品的多个候选来源（OR）；
  <b>圆角矩形 = 一条动作</b>：多条入边是它的并列前置（AND），缺一不可。
  <b>红色 = 最优的那条路线</b>（从原料一路走到 target）；
  连到 target 的边写的是整条路线的<b>整次总成本</b>，其它节点上是<b>单价 × 需要量</b>
  （`×1/9` 表示一次动作产出 9 件，这里只分摊九分之一）；{ramp_note}
  虚线框是展到深度上限的节点——它的成本已经算进去了，省掉的只是更下游的明细；
  路径上已经出现过的前置（环）直接不画。
</div>
<div class="card">{svg_text}</div>
<h2>路线对照</h2>
<table><thead><tr><th>名次</th><th>成本比</th><th>单价</th><th>整次</th>
<th>比最优</th><th></th></tr></thead><tbody>{body}</tbody></table>
</body></html>
"""


def write_outputs(
    base: Path, trees: list[PathTree], target: str, *, rankdir: str = "TB"
) -> list[str]:
    """写 `<base>.dot`，能画 SVG 时再写 `<base>.svg` 与 `<base>.html`。

    默认 `rankdir=TB`：来源在上、产物沉到最下面，读图顺序与施工顺序一致。
    """
    if not trees:
        return []
    stem = base.with_suffix("") if base.suffix else base
    if stem.parent and not stem.parent.exists():
        stem.parent.mkdir(parents=True, exist_ok=True)
    graph = to_path_graph(trees, target, rankdir=rankdir)
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
    html_path.write_text(render_html(svg_text, trees, target), encoding="utf-8")
    written.append(str(html_path))
    return written
