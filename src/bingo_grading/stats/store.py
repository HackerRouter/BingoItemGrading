"""统计快照的读写。

快照是一个目录（`data/stats/<pack>/`），分三个文件：

- `meta.json`：布局版本、地形包版本，以及**元数据表**——`note` / `derived_from` /
  `provenance` 去重后集中存放，行里只记下标 `m`；
- `spatial.jsonl`：可回退的空间测量（`SPATIAL_TYPES`）；
- `facts.jsonl`：命名事实（`FACT_TYPES`）。

早期版本把所有行写进一个 `world_stat.jsonl`，同一段说明在每行重复一遍。
拆开后说明只存一次；读盘时展开回 `WorldStat`，内存形状不变。
"""

from __future__ import annotations

import json
from pathlib import Path

from .model import FACT_TYPES, SPATIAL_TYPES, StatError, WorldStat, WorldStatStore

LAYOUT_VERSION = 2
META_NAME = "meta.json"
SPATIAL_NAME = "spatial.jsonl"
FACT_NAME = "facts.jsonl"

# 元数据三元组：`(note, derived_from, provenance)`。
MetaKey = tuple[str, tuple[str, ...], str]
EMPTY_META: MetaKey = ("", (), "")


def _meta_key(stat: WorldStat) -> MetaKey:
    return (stat.note, tuple(stat.derived_from), stat.provenance)


def _root(path: Path) -> Path:
    """快照目录。也接受旧的单文件路径（取其所在目录）。"""
    path = Path(path)
    if path.name.endswith(".jsonl") or path.name.endswith(".json"):
        return path.parent
    return path


def load(path: Path) -> WorldStatStore:
    """读一个快照目录。逐行报错，错误信息带行号。"""
    root = _root(path)
    entries = _read_meta(root)
    store = WorldStatStore()
    for name in (SPATIAL_NAME, FACT_NAME):
        target = root / name
        if target.exists():
            _load_jsonl(target, entries, store)
    if not store.rows:
        raise StatError(f"{root} 没有任何统计行")
    return store


def dump(store: WorldStatStore, path: Path) -> None:
    """按类别分文件、按主键排序写出，保证同一集合两次写出逐字节一致。"""
    root = _root(path)
    root.mkdir(parents=True, exist_ok=True)
    entries, index_of = _collect_meta(store)
    meta = {
        "layout_version": LAYOUT_VERSION,
        "pack_versions": sorted(store.pack_versions()),
        "notes": [
            {"note": note, "derived_from": list(derived), "provenance": provenance}
            for note, derived, provenance in entries
        ],
    }
    (root / META_NAME).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    groups: dict[str, list[dict]] = {SPATIAL_NAME: [], FACT_NAME: []}
    for stat in sorted(store.rows.values(), key=lambda item: item.key):
        name = SPATIAL_NAME if stat.stat_type in SPATIAL_TYPES else FACT_NAME
        groups[name].append(_row(stat, index_of))
    for name, rows in groups.items():
        text = "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows
        )
        (root / name).write_text(
            (text + "\n") if text else "", encoding="utf-8", newline="\n"
        )


def _row(stat: WorldStat, index_of: dict[MetaKey, int]) -> dict:
    """一行 JSON：元数据三元组折叠成 `m` 下标。"""
    data = stat.as_dict()
    data.pop("note", None)
    data.pop("derived_from", None)
    data.pop("provenance", None)
    key = _meta_key(stat)
    if key != EMPTY_META:
        data["m"] = index_of[key]
    return data


def _collect_meta(store: WorldStatStore) -> tuple[list[MetaKey], dict[MetaKey, int]]:
    """按首次出现顺序建立去重表（稳定，保证两次写出逐字节一致）。"""
    entries: list[MetaKey] = []
    index_of: dict[MetaKey, int] = {}
    for stat in sorted(store.rows.values(), key=lambda item: item.key):
        key = _meta_key(stat)
        if key == EMPTY_META or key in index_of:
            continue
        index_of[key] = len(entries)
        entries.append(key)
    return entries, index_of


def _read_meta(root: Path) -> list[MetaKey]:
    path = root / META_NAME
    if not path.exists():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    version = doc.get("layout_version")
    if version != LAYOUT_VERSION:
        raise StatError(
            f"{path} 的 layout_version={version!r}，只认 {LAYOUT_VERSION}；"
            "重跑 `bg data ingest` 与 `bg data loot` 生成新快照"
        )
    entries: list[MetaKey] = []
    for item in doc.get("notes") or []:
        entries.append(
            (
                item.get("note", ""),
                tuple(item.get("derived_from") or ()),
                item.get("provenance", ""),
            )
        )
    return entries


def _load_jsonl(path: Path, entries: list[MetaKey], store: WorldStatStore) -> None:
    text = Path(path).read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise StatError(f"{path}:{number} 不是合法 JSON：{exc}") from exc
        index = raw.pop("m", None)
        if index is not None:
            if not isinstance(index, int) or not 0 <= index < len(entries):
                raise StatError(
                    f"{path}:{number} 的 m={index!r} 越界（meta 表 {len(entries)} 条）"
                )
            note, derived, provenance = entries[index]
            raw["note"] = note
            raw["derived_from"] = list(derived)
            raw["provenance"] = provenance
        try:
            store.add(WorldStat.from_dict(raw))
        except StatError as exc:
            raise StatError(f"{path}:{number} {exc}") from exc
