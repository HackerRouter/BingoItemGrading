"""共享小工具：路径解析、JSON 输出、控制台兜底、档位与分数。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pathlib import Path
from .. import paths



ROOT = Path(__file__).resolve().parents[3]



def graph_path(label: str, override: str | None) -> Path:
    """上游可达性图的路径。优先项目自持快照，回退到 ref。"""
    if override:
        return Path(override)
    return paths.recipe_analysis(label).path / "graph.json"



def stats_path(pack: str, override: str | None) -> Path:
    """本项目自己的统计快照**目录**（`meta.json` + `spatial.jsonl` + `facts.jsonl`）。"""
    if override:
        return Path(override)
    return paths.STATS_ROOT / pack



def print_json(payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    try:
        print(text)
    except UnicodeEncodeError:
        # Windows 控制台不一定是 UTF-8（GBK 下 `²`/`³` 会直接抛错）。
        # 退回 ASCII 转义：内容不丢，只是非 ASCII 变 \uXXXX。
        print(json.dumps(payload, ensure_ascii=True, sort_keys=True))



def _tier(cost: float) -> int:
    from .units import tier_of

    return tier_of(cost)



def _score(cost: float) -> int:
    from .units import score_from_cost

    return score_from_cost(cost)



def _write_console(text: str) -> None:
    """打多行文本到终端：控制台编码装不下的字符降级成 `?`，不抛异常。

    Windows 默认 cp936，制表符/箭头一类常常装不下。图本身就是给人看的，
    退化成方框也比整条命令崩掉好。
    """
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode(encoding, "replace").decode(encoding, "replace"))



def _progress(total: int, desc: str):
    """进度条。没装 tqdm 时返回 `None`，功能不受影响，只是看不到进度。"""
    try:
        from tqdm import tqdm
    except ImportError:  # pragma: no cover - 依赖缺失时的降级
        return None
    return tqdm(total=total, desc=desc, unit="件", file=sys.stderr, dynamic_ncols=True)



def _close(bar) -> None:
    if bar is not None:
        bar.close()



def is_ore_subject(subject: str) -> bool:
    """矿石方块判定。统计侧只测了矿石的暴露密度，非矿石方块不需要它。"""
    name = subject.split(":", 1)[-1]
    return name.endswith("_ore") or name == "ancient_debris"



def index_path(label: str, override: str | None) -> Path:
    if override:
        return Path(override)
    return paths.BUILD_ROOT / label / "source_index.jsonl"
