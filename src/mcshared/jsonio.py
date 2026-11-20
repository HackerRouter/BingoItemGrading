"""JSON 读写：只认 UTF-8，失败即报错。

不吞异常：两个项目的红线都是「不认识的东西必须留痕」。读失败由调用方登记。
"""

from __future__ import annotations

import json
from pathlib import Path


class JsonError(ValueError):
    """文件不是合法 JSON，或顶层不是对象。"""


def read_json(path: Path) -> object:
    """读 JSON。文件不存在、解码失败、语法错误都抛 `JsonError`。"""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise JsonError(f"{path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise JsonError(f"{path}: {exc}") from exc


def read_json_object(path: Path) -> dict:
    """读 JSON 并断言顶层是对象。"""
    doc = read_json(path)
    if not isinstance(doc, dict):
        raise JsonError(f"{path}: 顶层不是对象")
    return doc


def dumps(value: object) -> str:
    """稳定的 JSON 文本：不做美化的 compact 输出，键序按调用方构造顺序。"""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
