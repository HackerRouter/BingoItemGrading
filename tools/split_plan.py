"""把 docs/planning/todo.md 按「全库联合计算」为界拆成界前 / 界后两册，另立当前待办。

界前 = 逐件问答时代的口径推导；界后 = 全图推理（一次建图、逐件抽取）确立之后的记录。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs" / "planning"
SOURCE = PLAN / "todo.md"

# 标题前缀 → 归属
BEFORE = (
    "## 刷怪权重",
    "## 按波次",
    "## 直接来源的主键撞车",
    "## 装备掉落与权重产出",
    "## 矿物暴露率接进 caving",
    "## 挂墙变体与结构方块的行程口径",
    "## 头颅机制与两处关联错",
    "## 交互类来源",
    "## 紫水晶洞",
    "## 鱼桶",
    "## 地下结构的搜索成本",
    "## 统一入口",
    "## 节点型来源",
    "## 构造模型",
    "## 箱子来源的两处口径错误",
    "## 取段组合的退化分支",
    "## 缺口报告去噪",
    "## 难度表",
)
AFTER = (
    "## 全库联合计算",
    "## 求解提速",
    "## 待改造：用 DAG 拓扑序",
    "## 方块来源改成多路并列",
    "## 全库联合口径与单件口径的对齐",
    "## 结构贡献占比",
)
TODO = ("## 成本口径", "## 其他积压")

BEFORE_LEAD = """界前指逐件问答时代：每次只为一件物品建图、求解，用一轮轮口径修正把单个数字拿准。
本册记的是那些推导与坑，按主题排列，不是时间顺序。
"""
AFTER_LEAD = """界后的判据是「全库联合计算给出的数就是唯一的数」：一次建图覆盖全部物品，一次求解拿全部曲线，再逐件取整次成本。
本册记全图口径的确立过程与遗留问题。
"""
TODO_LEAD = """未完成项按影响面排序。每条都指向具体文档或代码位置，能直接开工。
"""

SPEED = """## 未完成项速查

- **全图持久化**：把动作图落盘成 `build/<pack>/actions.jsonl`，查询复用。方案见 [`docs/impl/whole-graph-persistence.md`](../docs/impl/whole-graph-persistence.md)。
- **DAG 拓扑序替代分层迭代**：`solve` 现在是值迭代，跑 `max_level + 2` 层。拓扑 DP 是 `O(V + E)`，且单调收敛。三个已知坑记在 [`log/after-graph.md`](log/after-graph.md)。
- **首件口径的 Pareto 剪枝**：现在的候选取自「按均摊剪枝后留下的段」，被剪掉但首件更便宜的来源不参与比较，结果偏保守。
- **`p95` / `tail_score`**：评分定义里有尾部维度，`loot/expect.py` 只传播一阶矩。补二阶矩不需要新数据。
- **只由结构分布、又没有配方的方块**（`cobweb`、`torch`）：`block_density` 被当散点密度用。判据候选是「结构贡献占比」，但实测它不是二分类问题。
- **`assume:time`（铜自然氧化）45 条**：当前记「未建模的变换依赖」后跳过。接不接取决于「等它氧化」算不算合法路线。
- **`abandoned_camp_*` 10 个变体缺采集样本**：上游扩大扫描覆盖后才有逐实例口径。
"""


def split_sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    """返回 (导语, [(标题行, 段正文)])。"""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("## ")]
    lead = "\n".join(lines[: starts[0]]) if starts else text
    sections = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(lines)
        sections.append(("\n".join(lines[start:end]).strip(), lines[start]))
    return lead.strip(), sections


def pick(sections, prefixes):
    out = []
    for prefix in prefixes:
        matched = [body for body, title in sections if title.startswith(prefix)]
        if not matched:
            print(f"warn   找不到 {prefix!r}")
        out.extend(matched)
    return out


def main() -> None:
    (PLAN / "log").mkdir(exist_ok=True)
    lead, sections = split_sections(SOURCE.read_text(encoding="utf-8"))

    before = pick(sections, BEFORE)
    after = pick(sections, AFTER)
    todo = pick(sections, TODO)
    used = len(before) + len(after) + len(todo)
    if used != len(sections):
        missing = [
            title for _, title in sections if not any(title.startswith(p) for p in BEFORE + AFTER + TODO)
        ]
        print(f"warn   {len(sections) - used} 段未归类：{missing}")

    (PLAN / "log" / "before-graph.md").write_text(
        "# 界前：逐件建模\n\n" + BEFORE_LEAD + "\n" + "\n\n".join(before) + "\n",
        encoding="utf-8",
    )
    (PLAN / "log" / "after-graph.md").write_text(
        "# 界后：全图推理\n\n" + AFTER_LEAD + "\n" + "\n\n".join(after) + "\n",
        encoding="utf-8",
    )
    (PLAN / "todo.md").write_text(
        "# 待办\n\n" + TODO_LEAD + "\n" + SPEED + "\n" + "\n\n".join(todo) + "\n",
        encoding="utf-8",
    )
    print(f"before {len(before)} 段；after {len(after)} 段；todo {len(todo)} 段")


if __name__ == "__main__":
    main()
