"""把 plan 的两册日志再按主题分册，单个文件压到 200 行量级。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "plan" / "log"

GROUPS = {
    "sources-mobs.md": (
        "来源：生物与掉落",
        "生物与实体类来源的口径推导。",
        ("## 刷怪权重", "## 按波次", "## 装备掉落与权重产出", "## 交互类来源", "## 头颅机制"),
    ),
    "sources-intake.md": (
        "来源：统一入口与构造",
        "从手写案例转向「来源索引 → 动作图」时踩的坑。",
        ("## 鱼桶", "## 统一入口", "## 节点型来源", "## 构造模型", "## 箱子来源的两处口径错误"),
    ),
    "mining.md": (
        "挖掘模型",
        "矿石与方块的采集成本模型。",
        ("## 矿物暴露率接进 caving", "## 紫水晶洞", "## 地下结构的搜索成本"),
    ),
    "data-keys.md": (
        "统计口径与主键",
        "统计层的主键、变体命名与缺口去噪。",
        ("## 直接来源的主键撞车", "## 挂墙变体与结构方块的行程口径", "## 缺口报告去噪"),
    ),
    "engine.md": (
        "引擎与呈现",
        "取段组合与难度表的口径。",
        ("## 取段组合的退化分支", "## 难度表"),
    ),
    "after-graph.md": (
        "界后：全图计算",
        "一次建图覆盖全部物品，一次求解拿全部曲线。",
        ("## 全库联合计算", "## 求解提速", "## 待改造：用 DAG 拓扑序"),
    ),
    "after-routes.md": (
        "界后：来源并列与口径对齐",
        "让任意查询都能从同一张全图里取到同一批候选来源。",
        ("## 方块来源改成多路并列", "## 全库联合口径与单件口径的对齐", "## 结构贡献占比"),
    ),
}

# 源文件 → 该文件里的段归属哪些组
SOURCES = {
    "before-graph.md": ("sources-mobs.md", "sources-intake.md", "mining.md", "data-keys.md", "engine.md"),
    "after-old.md": ("after-graph.md", "after-routes.md"),
}


def split_sections(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("## ")]
    out = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(lines)
        out.append((lines[start], "\n".join(lines[start:end]).strip()))
    return out


def main() -> None:
    merged: list[tuple[str, str]] = []
    for source_name in SOURCES:
        path = LOG / source_name
        if not path.exists():
            print(f"skip   {source_name}")
            continue
        merged.extend(split_sections(path.read_text(encoding="utf-8")))

    assigned: set[int] = set()
    for target, (title, lead, prefixes) in GROUPS.items():
        picked = []
        for index, (heading, body) in enumerate(merged):
            if any(heading.startswith(prefix) for prefix in prefixes):
                picked.append(body)
                assigned.add(index)
        if not picked:
            print(f"warn   {target} 没有内容")
            continue
        (LOG / target).write_text(
            f"# {title}\n\n{lead}\n\n" + "\n\n".join(picked) + "\n", encoding="utf-8"
        )
        print(f"write  {target}（{len(picked)} 段）")

    left = [h for i, (h, _) in enumerate(merged) if i not in assigned]
    if left:
        print("warn   未归类：", left)

    for name in ("before-graph.md", "after-old.md"):
        path = LOG / name
        if path.exists():
            path.unlink()
            print(f"remove {name}")


if __name__ == "__main__":
    main()
