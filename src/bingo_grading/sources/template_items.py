"""模板里**直接放着**的物品：装饰罐里的陶片。

`binding:template-item:<容器>:<物品>` 这条来源上游只说「某个模板里放了这个容器，
容器里有这件东西」——没有战利品表名，因为陶片根本不在表里：它是模板 NBT 里
写进装饰罐 `sherds` 槽位的。所以不能用 `loot_expectation` 查，只能读模板本身。

数据是齐的，分两份：

- **采集侧** `structure-interior.*.json` 的 `templates[].perStart`：每个结构变体
  每处出现几次某个模板；
- **解析侧** `facts/template.jsonl` 的 `item_refs`：某个模板的某个 block entity
  里放了什么（`{holder: minecraft:decorated_pot, id: minecraft:flow_pottery_sherd,
  slot: sherds.back}`）。

两者相乘就是「在这个结构里跑一趟，平均能拿到几个」。这一步以前没人做，
于是 5 个陶片里 3 个在 `all.csv` 里永远算不出路线。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .. import paths

INDEX_PATTERN = "structure-interior.*.json"


@dataclass(frozen=True)
class Site:
    """某个结构变体每处能拿到几个目标物品。"""

    structure: str
    """结构变体 ID（`minecraft:trial_chambers`）。"""

    per_start: float
    """每处平均几个。"""


def _local(name: str) -> str:
    """`minecraft:village/plains/houses/a` → `village/plains/houses/a`。

    采集侧与解析侧的模板名一个带命名空间、一个不带，统一去掉再比。
    """
    return name.split(":", 1)[-1]


def _structure_templates(run_dir: Path) -> dict[str, dict[str, float]]:
    """结构变体 → `{模板: 每处出现次数}`。"""
    out: dict[str, dict[str, float]] = {}
    if not run_dir.is_dir():
        return out
    for path in sorted(run_dir.glob(INDEX_PATTERN)):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for payload in (doc.get("result") or {}).values():
            if not isinstance(payload, dict):
                continue
            for item in payload.get("structures") or []:
                if not isinstance(item, dict):
                    continue
                structure = item.get("structure")
                if not isinstance(structure, str):
                    continue
                counts = out.setdefault(structure, {})
                for entry in item.get("templates") or []:
                    if not isinstance(entry, dict):
                        continue
                    name = entry.get("template")
                    per_start = entry.get("perStart")
                    if (
                        isinstance(name, str)
                        and isinstance(per_start, (int, float))
                        and per_start > 0
                    ):
                        key = _local(name)
                        counts[key] = counts.get(key, 0.0) + float(per_start)
    return out


def _template_refs(facts_path: Path) -> dict[str, dict[str, dict[str, float]]]:
    """`{容器: {物品: {模板: 个数}}}`，来自模板 NBT 的 `item_refs`。"""
    table: dict[str, dict[str, dict[str, float]]] = {}
    if not facts_path.exists():
        return table
    with facts_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line).get("payload") or {}
            template = payload.get("template")
            if not isinstance(template, str):
                continue
            key = _local(template)
            for ref in payload.get("item_refs") or []:
                if not isinstance(ref, dict):
                    continue
                holder = ref.get("holder")
                item = ref.get("id")
                if not isinstance(holder, str) or not isinstance(item, str):
                    continue
                bucket = table.setdefault(holder, {}).setdefault(item, {})
                bucket[key] = bucket.get(key, 0.0) + 1.0
    return table


class TemplateItems:
    """模板里直接放的物品 → 每个结构每处几个。"""

    def __init__(
        self,
        structures: dict[str, dict[str, float]],
        refs: dict[str, dict[str, dict[str, float]]],
    ) -> None:
        self._structures = structures
        self._refs = refs

    def sites(self, container: str, item: str) -> tuple[Site, ...]:
        """装了 `item` 的 `container` 出现在哪些结构里、每处几个。"""
        counts = (self._refs.get(container) or {}).get(item)
        if not counts:
            return ()
        found: dict[str, float] = {}
        for structure, templates in self._structures.items():
            total = 0.0
            for template, copies in counts.items():
                per_start = templates.get(template)
                if per_start:
                    total += per_start * copies
            if total > 0:
                found[structure] = round(total, 4)
        return tuple(Site(name, amount) for name, amount in sorted(found.items()))


@lru_cache(maxsize=4)
def load(pack: str | None = None) -> TemplateItems:
    """读一遍模板 NBT 与结构模板分布。缺文件时返回空表（调用方按无数据处理）。"""
    if not pack:
        return TemplateItems({}, {})
    run = paths.collector_run(pack)
    facts = paths.template_facts(pack)
    structures = _structure_templates(Path(run.path)) if run.layer != paths.MISSING else {}
    refs = _template_refs(Path(facts.path)) if facts.layer != paths.MISSING else {}
    return TemplateItems(structures, refs)
