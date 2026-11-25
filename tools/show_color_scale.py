"""生成合成图的候选最浅色色表（自包含 HTML），按编号供人工挑选。

最浓色固定为 `route_graph_ra.colors.BEST_COLOR`；候选最浅色从深到浅编号 1..N。
每个候选展示 1.0 / 1.1 / 1.25 / 1.5 / 2.0 / 4.0 倍成本下的插值结果，
以及它与最浓色的亮度差——用来判断「数值差距很小的两条路线是否还能分辨」。

用法：

```bash
python tools/show_color_scale.py            # 写 build/color-scale.html
python tools/show_color_scale.py --out build/my-scale.html
```
"""

from __future__ import annotations

import argparse
from pathlib import Path

from bingo_grading.route_graph_ra.colors import BEST_COLOR, _mix, color_t

# 候选最浅色：保持蓝灰色相，从深到浅。编号从 1 开始（与页面一致）。
CANDIDATES = (
    "#2f5f82",
    "#3f7196",
    "#5585a9",
    "#6d9abc",
    "#86b0cd",
    "#9fc5db",
    "#b6d7e7",
    "#cbe6f0",
    "#dcf1f6",
    "#e9f7fa",
    "#f2fbfc",
    "#f8fdfe",
)

# 当前选中的最浅色编号（用户选定 8）。页面里标出这一行。
SELECTED = 8

# 成本比预览：前几个专门用来看「小差距」能不能分辨。
RATIOS = (1.0, 1.1, 1.25, 1.5, 2.0, 4.0)


def _luminance(color: str) -> float:
    """WCAG 相对亮度，用来比较两个颜色在感知上差多少。"""
    values = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
        for value in values
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(left: str, right: str) -> float:
    a, b = sorted((_luminance(left), _luminance(right)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def _swatch_cells(worst: str) -> str:
    cells = []
    for ratio in RATIOS:
        color = _mix(BEST_COLOR, worst, color_t(ratio))
        cells.append(
            f'<td><span class="chip" style="background:{color}"></span>'
            f'<code>{color}</code></td>'
        )
    return "".join(cells)


def render() -> str:
    head = "".join(f"<th>{ratio:g}×</th>" for ratio in RATIOS)
    rows = [
        f'<tr><td><span class="muted">最浓</span></td>'
        f'<td><span class="chip" style="background:{BEST_COLOR}"></span>'
        f"<code>{BEST_COLOR}</code></td>"
        f'<td><span class="muted">固定</span></td><td><code>0.000</code></td></tr>'
    ]
    for number, worst in enumerate(CANDIDATES, start=1):
        picked = " class=\"picked\"" if number == SELECTED else ""
        mark = " ✓ 已选" if number == SELECTED else ""
        rows.append(
            f"<tr{picked}><td><b>{number}</b>{mark}</td>"
            f'<td><span class="chip" style="background:{worst}"></span>'
            f"<code>{worst}</code></td>"
            f"<td>{_contrast(BEST_COLOR, worst):.2f}</td>"
            f"<td><code>{_luminance(worst) - _luminance(BEST_COLOR):+.3f}</code></td></tr>"
        )
    preview = "".join(
        f"<tr><td><b>{number}</b></td>{_swatch_cells(worst)}</tr>"
        for number, worst in enumerate(CANDIDATES, start=1)
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>合成图色表</title>
<style>
body {{ margin: 0; padding: 28px 32px 48px; background: #fbfbfc; color: #22262a;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; }}
h1 {{ font-size: 19px; margin: 0 0 6px; }}
h2 {{ font-size: 14px; margin: 26px 0 8px; }}
tr.picked td {{ background: #f0f9ff; }}
.sub {{ color: #8a9099; font-size: 13px; line-height: 1.8; margin-bottom: 16px; }}
table {{ border-collapse: collapse; font-size: 13px; background: #fff;
  border: 1px solid #e6e8eb; border-radius: 10px; overflow: hidden; }}
th, td {{ text-align: left; padding: 7px 14px; border-bottom: 1px solid #eef0f2; }}
th {{ color: #8a9099; font-weight: 600; background: #fafbfc; }}
.chip {{ display: inline-block; width: 34px; height: 16px; border-radius: 3px;
  vertical-align: -3px; margin-right: 8px; border: 1px solid #00000014; }}
code {{ font-size: 12px; color: #475569; }}
.muted {{ color: #8a9099; }}
</style></head><body>
<h1>合成图色表 · 选择最浅色</h1>
<div class="sub">
  最浓色固定为 <code>{BEST_COLOR}</code>。下面编号 1–{len(CANDIDATES)} 是候选最浅色；
  当前选中编号 <b>{SELECTED}</b>（<code>{CANDIDATES[SELECTED - 1]}</code>）。<br>
  实际画图时最浅色固定给「本图最差分支」，色阶在最优与最差之间铺满；
  预览列仍以 4× 作为参考端点。<br>
  「对比度」是与最浓色的 WCAG 对比度；「亮度差」是相对亮度的差值。
  数值越大，最浓与最浅越容易区分，但中间档也会被拉开。
</div>
<h2>候选最浅色</h2>
<table><thead><tr><th>编号</th><th>颜色</th><th>对比度</th><th>亮度差</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<h2>按比例插值预览</h2>
<div class="sub">列是「相对最优路线的成本比」。1.1× / 1.25× 用来检查小差距是否还能分辨。</div>
<table><thead><tr><th>编号</th>{head}</tr></thead><tbody>{preview}</tbody></table>
</body></html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="build/color-scale.html")
    args = parser.parse_args()
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(), encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
