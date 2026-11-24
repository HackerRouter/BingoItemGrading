"""把 `PathGraph` 渲染成 DOT / SVG。

同构副本，来源：`ref/RecipeAnalysis/src/ra/report/paths/render.py` 的
`build_dot` / `graphviz_available`。**本侧扩展了两处**，用 `本侧扩展`
标注：

- `info["html"]`：节点 label 用 Graphviz HTML-like label（可放宽行距）；
- `info["border"]`：节点边框按成本比着色（上游只在 root/leaf/target 上设）。

HTML 外壳由本包的 `html.py` 负责，保留本项目的「路线对照表」，不复用上游
`render_html` 的折叠统计。
"""

from __future__ import annotations

import subprocess

from .options import PathOptions
from .path_graph import PathGraph
from .style import DEFAULT_EDGE_COLOR, FILL, TARGET_BORDER, TARGET_FILL, short


def graphviz_available() -> bool:
    """`dot` 在不在 PATH 上。"""
    try:
        subprocess.run(["dot", "-V"], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def _attr(text: str) -> str:
    """DOT 属性值转义。双引号会提前结束属性，换行在 DOT 里必须是 `\\n`。"""
    return str(text).replace('"', "'").replace("\n", "\\n")


def build_dot(graph: PathGraph, options: PathOptions) -> str:
    """`PathGraph` → DOT 文本。

    不写图内标题。参数与计数由 HTML 的文字区承担。
    """
    lines = [
        "digraph sources {",
        f"  rankdir={options.rankdir};",
        "  nodesep=0.16; ranksep=0.48;",
        "  bgcolor=white;",
        '  node [shape=box, style="filled,rounded", fontname="Microsoft YaHei",'
        ' fontsize=10, penwidth=0.8, margin="0.10,0.04"];',
        '  edge [fontname="Microsoft YaHei", fontsize=8, arrowsize=0.6, penwidth=1.2];',
    ]

    for key, info in graph.nodes.items():
        sort = info.get("sort", "item")
        label = info.get("label") or short(key)
        # 本侧扩展：HTML-like label，允许用 <TABLE> 控制行距。
        label_attr = f"<{label}>" if info.get("html") else f'"{_attr(label)}"'

        if sort == "rule":
            # 本侧扩展：动作节点文字多，用矩形（菱形要按对角线撑开，极浪费）。
            rule_style = "dashed,filled" if info.get("cut") else "rounded,filled"
            rule_border = info.get("border") or "#94a3b8"
            lines.append(
                f'  "{_attr(key)}" [shape=box, style="{rule_style}",'
                f' fillcolor="{FILL["rule"]}",'
                f' color="{rule_border}", label={label_attr}, fontsize=9,'
                f' margin="0.08,0.03", fontcolor="#334155",'
                f' tooltip="{_attr(info.get("tooltip", ""))}"];'
            )
            continue

        if sort in {"group", "bucket"}:
            shape = "folder"
            fill = FILL["group"] if sort == "group" else FILL["bucket"]
            border = "#6366f1" if sort == "group" else "#94a3b8"
            font = "#3730a3" if sort == "group" else "#334155"
            lines.append(
                f'  "{_attr(key)}" [shape={shape}, style="filled",'
                f' fillcolor="{fill}", color="{border}", fontcolor="{font}",'
                f' fontsize="10", label={label_attr},'
                f' tooltip="{_attr(info.get("tooltip", ""))}"];'
            )
            continue

        if sort in {"omitted", "blocked"}:
            fill = FILL["omitted"] if sort == "omitted" else "#fef2f2"
            border = "#fb923c" if sort == "omitted" else "#dc2626"
            font = "#9a3412" if sort == "omitted" else "#991b1b"
            lines.append(
                f'  "{_attr(key)}" [shape=note, style="dashed,filled",'
                f' fillcolor="{fill}", color="{border}", fontcolor="{font}",'
                f' fontsize="9", label={label_attr},'
                f' tooltip="{_attr(info.get("tooltip", ""))}"];'
            )
            continue

        attrs: dict[str, str] = {
            "label": label_attr,
            "fillcolor": f'"{FILL.get(sort, "#f8fafc")}"',
            "tooltip": f'"{_attr(info.get("tooltip", ""))}"',
        }
        # 本侧扩展：物品节点用椭圆——名字短，椭圆比矩形省一圈边距，
        # 也和动作的矩形在形状上区分开。
        if sort == "item":
            attrs["shape"] = "ellipse"
        if sort == "template":
            attrs["shape"] = "note"
        if info.get("root"):
            attrs.update(shape="ellipse", penwidth="1.8", color='"#334155"')
        if info.get("leaf"):
            attrs["color"] = '"#0f766e"'
        if info.get("cut"):
            attrs.update(style='"dashed,filled"', color='"#94a3b8"')
        # 本侧扩展：节点边框按成本比着色。
        if info.get("border"):
            attrs["color"] = f'"{info["border"]}"'
        if key == graph.target:
            attrs.update(
                fillcolor=f'"{TARGET_FILL}"',
                color=f'"{TARGET_BORDER}"',
                penwidth="2.4",
                peripheries="2",
                fontsize="13",
                fontcolor='"#78350f"',
            )
        lines.append(
            f'  "{_attr(key)}" [{", ".join(f"{k}={v}" for k, v in attrs.items())}];'
        )

    # 本侧扩展：target 钉在最低一层，产物永远沉在整张图最下面。
    if graph.target and graph.target in graph.nodes:
        lines.append(f'  {{ rank=sink; "{_attr(graph.target)}"; }}')

    for (source, target, tag), (label, tooltip) in sorted(graph.edges.items()):
        color = graph.edge_colors.get((source, target, tag), DEFAULT_EDGE_COLOR)
        extra = ""
        if (source, target, tag) in graph.dashed:
            # 环边不参与层级计算：否则会把 target 从最底部推起来。
            extra = ", style=dashed, arrowhead=none, constraint=false"
        elif (source, target, tag) in graph.condition_edges:
            extra = ", style=dashed"
        if label == "（环）":
            extra = ", style=dashed"
        lines.append(
            f'  "{_attr(source)}" -> "{_attr(target)}" [label="{_attr(label)}",'
            f' color="{color}", fontcolor="{color}",'
            f' tooltip="{_attr(tooltip)}"{extra}];'
        )

    lines.append("}")
    return "\n".join(lines) + "\n"


def dot_to_svg(dot_text: str) -> str | None:
    """DOT → SVG；`dot` 缺失或语法错误时返回 `None`。"""
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
