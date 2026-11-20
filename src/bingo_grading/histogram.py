"""难度直方图：把全库成本分布画出来，并标出「下界 / 末地门口」在哪。

给 `bg grade` 用。两种输出：

- `render_text`：终端 ASCII 版，一行一档，条形按主导维度上色字符；
- `render_html`：自包含 HTML（内嵌 SVG），三个维度分色堆积，两条竖线是
  下界/末地入口的代价线。

**横轴是 `score`**，每 1 分 = 成本 ×√2（见 `units.SCORE_STEP`），所以相邻两格
就是"耗时翻倍"。成本是对数刻度，肉眼看到的距离就是难度差。

维度归属不是看物品"通常在哪拿"，而是看**能不能不用那道门拿到**：
`solve.unreachable_without(nether_access)` 给出「不用下界就拿不到」的物品集
（AND-OR 图上的最小可达集不动点）。于是「铁锭」算主世界（挖矿也能得，猪灵交易
只是备选），「远古残骸」算下界，「鞘翅」算末地。这比按结构位置硬编码可靠：
多一条主世界来源就能自动改判。
"""

from __future__ import annotations

import html
import math
from dataclasses import dataclass, field

from .plan.solve import unreachable_without
from .units import SECONDS_PER_TU, score_bounds, score_of_cost

EARTH = "earth"
NETHER = "nether"
END = "end"

DIMENSIONS = (EARTH, NETHER, END)
DIM_LABEL = {EARTH: "主世界", NETHER: "下界后", END: "末地后"}
DIM_COLOR = {EARTH: "#3aa757", NETHER: "#c0392b", END: "#c8b07a"}
# 终端版用的填充字符：主世界实心、下界斜纹、末地下半块。
# 只能用 GBK 装得下的字符——Windows 控制台默认 cp936，`▒` / `⟵` 这类
# 会直接抛 UnicodeEncodeError 把命令弄挂。实测 `█` `▓` `▄` 都安全。
DIM_CHAR = {EARTH: "█", NETHER: "▓", END: "▄"}

NETHER_ACCESS = "capability:nether_access"
THE_END_ACCESS = "capability:the_end_access"

# 要画成竖线的门槛：`(能力名, 图例标签, 线色)`。线色比柱色深，压得住背景。
GATES = (
    (NETHER_ACCESS, "下界入口", "#7b1f14"),
    (THE_END_ACCESS, "末地入口", "#7a5c1f"),
)


@dataclass(frozen=True)
class Mark:
    """一条竖线：某个门槛的代价。"""

    label: str
    cost: float
    color: str

    @property
    def score(self) -> float:
        """成本落在横轴的哪个位置（连续分值，不是取整后的档位）。"""
        return score_of_cost(self.cost) if self.cost > 0 else 0.0


@dataclass(frozen=True)
class Bin:
    """一个分数档：三个维度各多少件。"""

    score: int
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def low(self) -> float:
        """这一档的整次成本下界（TU）。0 档按 0 处理。"""
        return 0.0 if self.score == 0 else score_bounds(self.score)[0]

    @property
    def high(self) -> float:
        return score_bounds(self.score)[1]


@dataclass(frozen=True)
class Meta:
    """报告头：数据从哪来、总共多少件。"""

    pack: str
    items: int
    scored: int
    demand: float = 1.0

    @property
    def unscored(self) -> int:
        return self.items - self.scored


def classify(actionset) -> dict[str, str]:
    """物品 → 它最早能在哪个维度拿到（`earth` / `nether` / `end`）。

    末地本身要过下界（烈焰粉），所以「必须末地」是「必须下界」的子集，
    判断顺序不能反。
    """
    producers: dict[str, list] = {}
    for action in actionset.actions:
        for item in action.yields:
            producers.setdefault(item, []).append(action)
    blocked_by_end = unreachable_without(THE_END_ACCESS, producers)
    blocked_by_nether = unreachable_without(NETHER_ACCESS, producers)
    out: dict[str, str] = {}
    for item in producers:
        if item in blocked_by_end:
            out[item] = END
        elif item in blocked_by_nether:
            out[item] = NETHER
        else:
            out[item] = EARTH
    return out


def build_bins(rows, dimensions: dict[str, str]) -> list[Bin]:
    """按 `score` 分档，每档清点三个维度各多少件。

    没有分数的物品（算不出可行路线）不进直方图，`Meta.unscored` 单独报。
    """
    tally: dict[int, dict[str, int]] = {}
    for row in rows:
        if row.score is None:
            continue
        bucket = tally.setdefault(row.score, {key: 0 for key in DIMENSIONS})
        bucket[dimensions.get(row.item, EARTH)] += 1
    if not tally:
        return []
    empty = {key: 0 for key in DIMENSIONS}
    return [
        Bin(score=score, counts=tally.get(score, empty))
        for score in range(max(tally) + 1)
    ]


def totals(bins: list[Bin]) -> dict[str, int]:
    out = {key: 0 for key in DIMENSIONS}
    for item in bins:
        for key in DIMENSIONS:
            out[key] += item.counts.get(key, 0)
    return out


# ---------------------------------------------------------------- 终端版


def _split(counts: dict[str, int], width: int) -> list[int]:
    """把 `width` 个字符按三个维度的件数比例切开，余数按小数部分分配。"""
    total = sum(counts.get(key, 0) for key in DIMENSIONS)
    if total <= 0 or width <= 0:
        return [0, 0, 0]
    raw = [counts.get(key, 0) / total * width for key in DIMENSIONS]
    parts = [int(value) for value in raw]
    left = width - sum(parts)
    order = sorted(range(len(raw)), key=lambda i: raw[i] - parts[i], reverse=True)
    for index in order[: max(0, left)]:
        parts[index] += 1
    return parts


def render_text(bins: list[Bin], marks: list[Mark], meta: Meta, *, width: int = 36) -> str:
    """终端直方图：一行一档，条形用维度字符拼，门槛线挂在对应档的末尾。"""
    if not bins:
        return "（没有可统计的物品）"
    biggest = max(item.total for item in bins)
    per_dim = totals(bins)
    lines = [
        f"难度分布 · {meta.pack} · {meta.items} 件"
        f"（有分数 {meta.scored}，算不出 {meta.unscored}）",
        "",
        f"{'分数':>4}  {'整次成本':<16}{'条形':<{width}}  {'合计':>5}  "
        f"{'主世界':>5}{'下界':>5}{'末地':>5}",
    ]
    for item in bins:
        span = width if biggest <= 0 else max(1 if item.total else 0, round(item.total / biggest * width))
        parts = _split(item.counts, span)
        bar = "".join(
            DIM_CHAR[key] * parts[index] for index, key in enumerate(DIMENSIONS)
        )
        span_text = (
            f"<{item.high:.2f}"
            if item.score == 0
            else f"{item.low:.2f}~{item.high:.2f}"
        )
        tail = ""
        for mark in marks:
            if item.score - 0.5 <= mark.score < item.score + 0.5:
                tail = f"   <-- {mark.label} {mark.cost:.2f} TU"
                break
        lines.append(
            f"{item.score:>4}  {span_text:<16}{bar:<{width}}  {item.total:>5}  "
            f"{item.counts.get(EARTH, 0):>5}{item.counts.get(NETHER, 0):>5}"
            f"{item.counts.get(END, 0):>5}{tail}"
        )
    lines.append("")
    lines.append(
        "图例  "
        + "  ".join(
            f"{DIM_CHAR[key]} {DIM_LABEL[key]} {per_dim[key]}"
            for key in DIMENSIONS
        )
        + "    <-- 该档内有一条门槛线"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------- HTML 版


def _esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def render_svg(bins: list[Bin], marks: list[Mark], *, width: int = 1180) -> str:
    """堆积柱状 SVG。横轴是分数档，纵轴是件数，竖线是门槛代价。"""
    if not bins:
        return ""
    rows = len(bins)
    top, bottom = 64, 132
    left, right = 78, 30
    height = 660
    plot_w = width - left - right
    plot_h = height - top - bottom
    step = plot_w / rows
    bar_w = step * 0.82
    biggest = max(item.total for item in bins)
    # 顶部留 8% 空隙，否则 495/500 的柱子看起来是贴着顶的。
    ceiling = max(10, math.ceil(biggest * 1.08 / 50) * 50)
    # 档数多（新口径 30 档）时隔一档标一次横轴，否则字会叠。
    label_every = 1 if rows <= 14 else 2

    def y(value: float) -> float:
        return top + plot_h * (1 - value / ceiling)

    def x(score: float) -> float:
        """横轴坐标：档位 `score` 的柱子左边界。"""
        return left + score * step

    parts: list[str] = []
    # 横向网格
    ticks = 5
    for index in range(ticks + 1):
        value = ceiling * index / ticks
        line_y = y(value)
        parts.append(
            f'<line x1="{left}" y1="{line_y:.1f}" x2="{left + plot_w}" '
            f'y2="{line_y:.1f}" stroke="#e6e8eb" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{left - 10}" y="{line_y + 4:.1f}" text-anchor="end" '
            f'fill="#8a9099" font-size="12">{value:.0f}</text>'
        )

    # 柱
    for item in bins:
        base = x(item.score) + (step - bar_w) / 2
        cursor = 0
        for key in DIMENSIONS:
            count = item.counts.get(key, 0)
            if count <= 0:
                continue
            high = y(cursor + count)
            low = y(cursor)
            parts.append(
                f'<rect x="{base:.1f}" y="{high:.1f}" width="{bar_w:.1f}" '
                f'height="{low - high:.1f}" fill="{DIM_COLOR[key]}" '
                f'stroke="#ffffff" stroke-width="0.6"/>'
            )
            if count >= biggest * 0.05:
                parts.append(
                    f'<text x="{base + bar_w / 2:.1f}" y="{(high + low) / 2 + 4:.1f}" '
                    f'text-anchor="middle" fill="#ffffff" font-size="11" '
                    f'font-weight="600">{count}</text>'
                )
            cursor += count
        parts.append(
            f'<title>{item.score} 分：共 {item.total} 件'
            f'（主世界 {item.counts.get(EARTH, 0)}、'
            f'下界后 {item.counts.get(NETHER, 0)}、'
            f'末地后 {item.counts.get(END, 0)}）</title>'
        )
        # 横轴：分数、成本区间、时长。档数多时隔档标，否则字会叠在一起。
        if item.score % label_every:
            continue
        center = base + bar_w / 2
        parts.append(
            f'<text x="{center:.1f}" y="{top + plot_h + 24}" text-anchor="middle" '
            f'fill="#33383d" font-size="13" font-weight="600">{item.score}</text>'
        )
        span = f"&lt;{item.high:.2f}" if item.score == 0 else f"{item.low:.2f}~{item.high:.2f}"
        parts.append(
            f'<text x="{center:.1f}" y="{top + plot_h + 41}" text-anchor="middle" '
            f'fill="#8a9099" font-size="10">{span}</text>'
        )
        # 时长取该档**上界**：读作「这一档的东西最多花这么久」。
        parts.append(
            f'<text x="{center:.1f}" y="{top + plot_h + 56}" text-anchor="middle" '
            f'fill="#a5abb2" font-size="10">{_duration(item.high)}</text>'
        )

    # 门槛竖线
    for mark in marks:
        if not (bins[0].score - 0.5 <= mark.score <= bins[-1].score + 0.5):
            continue
        line_x = left + (mark.score + 0.5) * step
        parts.append(
            f'<line x1="{line_x:.1f}" y1="{top - 14}" x2="{line_x:.1f}" '
            f'y2="{top + plot_h}" stroke="{mark.color}" stroke-width="2" '
            f'stroke-dasharray="7 4"/>'
        )
        parts.append(
            f'<text x="{line_x + 6:.1f}" y="{top - 20}" fill="{mark.color}" '
            f'font-size="12" font-weight="600">{_esc(mark.label)} '
            f'{mark.cost:.2f} TU</text>'
        )

    axis_y = top + plot_h
    parts.append(
        f'<line x1="{left}" y1="{axis_y}" x2="{left + plot_w}" y2="{axis_y}" '
        f'stroke="#c6ccd2" stroke-width="1.5"/>'
    )
    parts.append(
        f'<text x="{left}" y="{top + plot_h + 82}" fill="#33383d" '
        f'font-size="12" font-weight="600">分数（每 1 分 = 成本 ×√2，每 2 分翻倍）'
        f"　·　下行是整次成本区间　·　最下行是约合时长</text>"
    )
    parts.append(f'<title>难度分布直方图</title>')
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" '
        f'preserveAspectRatio="xMidYMid meet" '
        f'font-family="-apple-system,BlinkMacSystemFont,\'Segoe UI\','
        f'\'Microsoft YaHei\',sans-serif" role="img">'
        + "".join(parts)
        + "</svg>"
    )


def _duration(tu: float) -> str:
    """TU → 人读时长。口径直接取 `units.SECONDS_PER_TU`，不在这里另存一份。"""
    seconds = tu * SECONDS_PER_TU
    if seconds < 60:
        return f"{seconds:.0f} 秒"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.0f} 分"
    return f"{minutes / 60:.1f} 小时"


def render_html(bins: list[Bin], marks: list[Mark], meta: Meta) -> str:
    """自包含 HTML（无外部资源），图标 + 图例 + 分维度统计。"""
    per_dim = totals(bins)
    scored = sum(per_dim.values())
    legend = "".join(
        f'<span class="swatch" style="background:{DIM_COLOR[key]}"></span>'
        f'<span class="legend-label">{_esc(DIM_LABEL[key])}'
        f'<b>{per_dim[key]}</b>'
        f'<i>{per_dim[key] / scored:.1%}</i></span>'
        for key in DIMENSIONS
    )
    lines = "".join(
        f"<tr><td>{mark.label}</td><td>{mark.cost:.2f} TU</td>"
        f"<td>{_duration(mark.cost)}</td><td>{mark.score:.2f}</td></tr>"
        for mark in marks
    )
    gate_table = (
        f"<table><thead><tr><th>门槛</th><th>整次成本</th><th>约合时长</th>"
        f"<th>落在横轴</th></tr></thead><tbody>{lines}</tbody></table>"
        if lines
        else '<p class="muted">没有算出下界/末地的入口代价。</p>'
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>难度分布 · {_esc(meta.pack)}</title>
<style>
:root {{ color-scheme: light dark; }}
body {{ margin: 0; padding: 28px 32px 48px; background: #fbfbfc; color: #22262a;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; }}
h1 {{ font-size: 19px; margin: 0 0 4px; }}
.sub {{ color: #8a9099; font-size: 13px; margin-bottom: 18px; }}
.card {{ background: #fff; border: 1px solid #e6e8eb; border-radius: 10px;
  padding: 18px 20px 10px; box-shadow: 0 1px 2px rgba(16,24,40,.04); }}
.legend {{ display: flex; gap: 22px; flex-wrap: wrap; margin: 6px 0 14px; font-size: 13px; }}
.legend-label {{ display: inline-flex; align-items: baseline; gap: 6px; }}
.legend-label b {{ font-size: 15px; }}
.legend-label i {{ color: #8a9099; font-style: normal; font-size: 12px; }}
.swatch {{ display: inline-block; width: 13px; height: 13px; border-radius: 3px;
  margin-right: 7px; vertical-align: -1px; }}
table {{ border-collapse: collapse; font-size: 13px; margin-top: 6px; }}
th, td {{ text-align: left; padding: 5px 16px 5px 0; border-bottom: 1px solid #eef0f2; }}
th {{ color: #8a9099; font-weight: 600; }}
.muted {{ color: #8a9099; font-size: 13px; }}
h2 {{ font-size: 14px; margin: 22px 0 8px; }}
</style></head><body>
<h1>难度分布 · {_esc(meta.pack)}</h1>
<div class="sub">{meta.items} 件物品，其中 {scored} 件算了分数，
{_esc(str(meta.unscored))} 件算不出可行路线（不进直方图）；每件按 {meta.demand:g} 个计。</div>
<div class="card">
  <div class="legend">{legend}
    <span class="legend-label muted">虚线 = 进入该维度的<b>最低</b>成本
      （档位是整档，会略微左溢）</span>
  </div>
  {render_svg(bins, marks)}
</div>
<h2>门槛代价</h2>
{gate_table}
</body></html>
"""
