"""村民交易的语法归一。

交易数据的形状分两层（标签层归 tags 适配器）：

| 层 | 形状 | 内容 |
|---|---|---|
| 单条交易 | `{gives, wants, max_uses, ...}` | 给什么、要什么 |
| 交易组 | `{amount, trades: "#tag"}` | 职业+等级 → 交易标签 |

`wants` 与 `gives` 的写法与配方产出同构（`{id, count, components}`），
但**语义不同**：`wants` 是支付、`gives` 是所得。这一层区分不归语法层，
这里只把两侧都归一成同一形状。

路径也是语法：`<职业>/<等级>/<名>.json` 与 `level_<N>.json` 两种排布，
由 `trade_id` / `segment` / `level` 还原。
"""

from __future__ import annotations

SCHEMA_VERSION = 1


def parse_item_stack(node: object) -> dict | None:
    """`{id, count, components}` → 归一形状。也接受裸字符串。"""
    if isinstance(node, str):
        return {"id": node, "count": 1}
    if not isinstance(node, dict):
        return None
    ident = node.get("id") or node.get("item")
    if not isinstance(ident, str):
        return None
    out: dict = {"id": ident}
    count = node.get("count", node.get("amount", 1))
    out["count"] = count if isinstance(count, int) else 1
    for key in ("components", "count_range"):
        if key in node:
            out[key] = node[key]
    # 未归一的字段原样留着，由调用方决定是不是前置
    rest = {k: v for k, v in node.items() if k not in ("id", "item", "count", "amount")}
    if rest:
        out["extra"] = rest
    return out


def trade_id(file_label: str, dirname: str, namespace: str) -> str:
    """`.../villager_trade/<职业>/<等级>/<名>.json` → `minecraft:<职业>/<等级>/<名>`。"""
    marker = f"/{dirname}/"
    if marker in file_label:
        return f"{namespace}:{file_label.partition(marker)[2][:-5]}"
    return file_label[:-5]


def segment(file_label: str, dirname: str, index: int) -> str | None:
    """交易路径是 `<职业>/<等级>/<名>.json`，取第 index 段。"""
    marker = f"/{dirname}/"
    if marker not in file_label:
        return None
    parts = file_label.partition(marker)[2].split("/")
    return parts[index] if len(parts) > index + 1 else None


def level(file_label: str, dirname: str) -> int | None:
    """取等级。交易组是 `level_N.json`，单条交易是 `<职业>/<N>/<名>.json`。"""
    marker = f"/{dirname}/"
    if marker not in file_label:
        return None
    parts = file_label.partition(marker)[2].split("/")

    for part in parts[1:]:
        stem = part[:-5] if part.endswith(".json") else part
        if stem.startswith("level_"):
            tail = stem[len("level_") :]
            return int(tail) if tail.isdigit() else None
        if stem.isdigit():
            return int(stem)
    return None
