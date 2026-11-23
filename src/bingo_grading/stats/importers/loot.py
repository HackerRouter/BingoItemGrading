"""战利品期望 → `loot_expectation` 统计行。

## 两种主键粒度

1. **按表**：`subject` = 战利品表 ID（`minecraft:chests/simple_dungeon`）。
   这是引擎能算得最准的粒度，一个箱子开一次的期望产出。
2. **按结构集合**：`subject` = 结构集合（`minecraft:villages`）。
   这是来源索引的 `stat_subject`，下游按它查。需要把该集合下所有箱子表
   按箱子数加权平均。

两种都写：按表给诊断用，按集合给下游用。

## 工具条件是两行

同一张表在「带工具」与「徒手」下期望不同（树叶最明显）。用 `condition`
区分：`tools=present` / `tools=absent`。两者都是合法主键，共存不冲突。

## 箱子数从哪来

上游 `template.jsonl` 的 `loot_tables: [{pos, table}]` 给出每个模板挂了哪些箱子。
`chests_per_structure` 取该结构集合下模板箱子数的**中位数**，并在 `note` 里写明
「按模板统计，未模拟 jigsaw 拼装」。这是近似，不当作精确值。
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from ...loot.expect import TableExpectation, expect
from ...loot.tables import LootTableSet
from ..model import WorldStat

# 条件取值，写进主键。
CONDITION_TOOLS_PRESENT = "tools=present"
CONDITION_TOOLS_ABSENT = "tools=absent"

TOOL_VARIANTS = (
    (CONDITION_TOOLS_PRESENT, 1.0),
    (CONDITION_TOOLS_ABSENT, 0.0),
)

# 表路径前缀 → 触发方式。这是「直接来源」的统一口径：
# 破坏/击杀/开箱/剪毛/刷扫都算「一次触发」，产出按件计。
TRIGGER_BY_PREFIX: dict[str, str] = {
    "blocks": "block_break",
    "harvest": "block_break",
    "carve": "block_break",
    "till": "block_break",
    "entities": "kill",
    "charged_creeper": "kill",
    "shearing": "shear",
    "archaeology": "brush",
    "pots": "brush",
    "chests": "chest_open",
    "barrels": "chest_open",
    "dispensers": "chest_open",
    "equipment": "chest_open",
    "spawners": "chest_open",
    "gameplay": "chest_open",
    "brush": "chest_open",
}

# 箱子以外的触发方式：对象名就是表路径前缀之后的部分。
SUBJECT_FROM_NAME = frozenset({"block_break", "kill", "shear", "brush"})

# 这些目录下的文件名是**子表名**，不是来源对象：`charged_creeper/root` /
# `charged_creeper/creeper` 里的 `creeper` 不是实体 ID。按实体取 subject 会让它
# 撞上 `entities/creeper`（那边只有火药），头颅类物品查期望时就会拿到错表。
# 与 `sources/classify.py` 的 `KEEP_PREFIXES` 必须一致。
KEEP_TABLE_PATH = frozenset({"charged_creeper"})


@dataclass
class StructureLoot:
    """一个结构集合的箱子构成。"""

    set_id: str
    # 表 ID → 该集合下出现该表的箱子数（跨模板累加）
    table_chests: Counter = field(default_factory=Counter)
    # 每个模板的箱子数，用于取中位数
    per_template: list[int] = field(default_factory=list)

    @property
    def chests_per_structure(self) -> float:
        if not self.per_template:
            return 0.0
        ordered = sorted(self.per_template)
        return float(ordered[len(ordered) // 2])

    @property
    def total_chests(self) -> int:
        return sum(self.table_chests.values())


class TemplateError(ValueError):
    """模板事实不可用。"""


def read_structure_loot(template_facts: Path, set_for_template) -> dict[str, StructureLoot]:
    """从上游 `template.jsonl` 读「结构集合 → 箱子构成」。

    `set_for_template` 是 `StructureMaps.set_for_template`，用于把模板路径
    映射到结构集合。映射不到的模板计入返回值之外的 `unmapped`（见 `build`）。
    """
    path = Path(template_facts)
    if not path.exists():
        raise TemplateError(f"模板事实不存在：{path}")

    out: dict[str, StructureLoot] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        payload = row.get("payload") or {}
        loot = payload.get("loot_tables") or []
        if not loot:
            continue
        template = payload.get("template")
        if not isinstance(template, str):
            continue
        set_id = set_for_template(template)
        if set_id is None:
            continue
        entry = out.setdefault(set_id, StructureLoot(set_id=set_id))
        entry.per_template.append(len(loot))
        for cell in loot:
            table = cell.get("table") if isinstance(cell, dict) else None
            if isinstance(table, str):
                entry.table_chests[table] += 1
    return out


def build(
    *,
    tables: LootTableSet,
    structure_loot: dict[str, StructureLoot],
    pack_version: str,
    dimension: str,
    structure_density: dict[str, dict] | None = None,
    provenance: str = "",
    tags: object | None = None,
) -> tuple[list[WorldStat], dict]:
    """生成统计行。返回 `(行, 报告)`。

    `structure_density` 是「结构集合 → value」的字典，用来填 `structure_frequency`。
    缺省时该字段留空，不填零。
    """
    rows: list[WorldStat] = []
    report: dict = {
        "per_table": 0,
        "per_structure": 0,
        "unsupported_tables": {},
        "missing_tables": [],
    }
    structure_density = structure_density or {}

    # ---- 1. 按表 ----
    for set_id, loot in sorted(structure_loot.items()):
        for table_id in sorted(loot.table_chests):
            if table_id not in tables:
                report["missing_tables"].append(table_id)
                continue
            for condition, tool_probability in TOOL_VARIANTS:
                result = expect(
                    table_id, tables, tool_probability=tool_probability, tags=tags
                )
                rows.append(
                    WorldStat(
                        pack_version=pack_version,
                        scope_level="dimension",
                        dimension=dimension,
                        biome="",
                        stat_type="loot_expectation",
                        subject=table_id,
                        condition=condition,
                        value=_table_value(result, loot),
                        sample_size=0,
                        confidence="medium",
                        derived_from=("rolls", "weight", "set_count"),
                        provenance=provenance,
                        note=(
                            "单个箱子开一次的期望产出；按表计，未按结构聚合。"
                            "工具条件见 condition；附魔按无附魔级"
                        ),
                    )
                )
                report["per_table"] += 1
                if result.unsupported:
                    report["unsupported_tables"][table_id] = result.unsupported

    # ---- 2. 按结构集合 ----
    for set_id, loot in sorted(structure_loot.items()):
        if not loot.total_chests:
            continue
        density = structure_density.get(set_id) or {}
        for condition, tool_probability in TOOL_VARIANTS:
            per_item: dict[str, float] = {}
            # 二阶矩加权和：多张表按出现频率混合时，方差不能各自相加，
            # 得用混合分布的 `E[X²] - E[X]²`。
            second: dict[str, float] = {}
            assumptions: set[str] = set()
            unsupported: set[str] = set()
            weight_sum = 0
            for table_id, chest_count in loot.table_chests.items():
                if table_id not in tables:
                    continue
                result = expect(
                    table_id, tables, tool_probability=tool_probability, tags=tags
                )
                weight_sum += chest_count
                for item_id, value in result.per_item.items():
                    per_item[item_id] = per_item.get(item_id, 0.0) + value * chest_count
                    spread = result.variance.get(item_id, 0.0)
                    second[item_id] = (
                        second.get(item_id, 0.0) + (spread + value * value) * chest_count
                    )
                assumptions.update(result.assumptions)
                unsupported.update(result.unsupported)
            if not weight_sum:
                continue
            # 按表出现频率加权，得到「随便开一个该结构的箱子」的期望。
            value: dict = {
                "per_trigger_expected": {
                    item_id: round(total / weight_sum, 4)
                    for item_id, total in sorted(per_item.items())
                    if total
                },
                "trigger": "chest_open",
            }
            spreads: dict[str, float] = {}
            for item_id, total in per_item.items():
                mean = total / weight_sum
                if mean <= 0:
                    continue
                e2 = second.get(item_id, 0.0) / weight_sum
                variance = max(0.0, e2 - mean * mean)
                if variance <= 0:
                    continue
                spreads[item_id] = round(math.sqrt(variance) / mean, 6)
            if spreads:
                value["per_trigger_cv"] = spreads
            chests = loot.chests_per_structure
            if chests:
                value["chests_per_structure"] = chests
            frequency = _frequency(density)
            if frequency is not None:
                value["structure_frequency"] = frequency
            if assumptions:
                value["assumptions"] = sorted(assumptions)
            if unsupported:
                value["unsupported"] = sorted(unsupported)

            rows.append(
                WorldStat(
                    pack_version=pack_version,
                    scope_level="dimension",
                    dimension=dimension,
                    biome="",
                    stat_type="loot_expectation",
                    subject=set_id,
                    condition=condition,
                    value=value,
                    sample_size=len(loot.per_template),
                    confidence="low" if chests and len(loot.per_template) < 3 else "medium",
                    derived_from=("loot_table", "template.loot_tables"),
                    provenance=provenance,
                    note=(
                        "按结构集合聚合：箱子数取模板中位数，未模拟 jigsaw 拼装；"
                        "per_trigger_expected 是该集合下任一箱子开一次的期望"
                    ),
                )
            )
            report["per_structure"] += 1

    return rows, report


def _table_value(result: TableExpectation, loot: StructureLoot) -> dict:
    value: dict = {
        "per_trigger_expected": {
            item_id: round(amount, 4)
            for item_id, amount in sorted(result.per_item.items())
            if amount
        },
        "trigger": "chest_open",
        "table": result.table,
    }
    spreads = _cv_map(result)
    if spreads:
        value["per_trigger_cv"] = spreads
    if result.assumptions:
        value["assumptions"] = list(result.assumptions)
    if result.unsupported:
        value["unsupported"] = list(result.unsupported)
    return value


def _cv_map(result: TableExpectation) -> dict[str, float]:
    """一张表：每件物品**一次触发**产出的相对标准差（`sd / mean`）。

    0 的不写（全是确定量时整个键省掉），下游按「无方差信息」处理。
    这批数是 `plan` 层 `Segment.cv` 的唯一上游。
    """
    out: dict[str, float] = {}
    for item_id, mean in result.per_item.items():
        if mean <= 0:
            continue
        variance = result.variance.get(item_id, 0.0)
        if variance <= 0:
            continue
        out[item_id] = round(math.sqrt(variance) / mean, 6)
    return out


def build_drops(
    *,
    tables: LootTableSet,
    pack_version: str,
    provenance: str = "",
    skip: frozenset[str] = frozenset(),
    tags: object | None = None,
) -> tuple[list[WorldStat], dict]:
    """方块 / 生物 / 剪毛 / 刷扫的「一次触发的期望产出」。

    箱子表由 `build()` 负责——它从模板事实知道箱子挂在哪个结构上，能给
    `chests_per_structure` 与 `structure_frequency`。这里跳过 `skip` 里的表，
    避免同主键互相覆盖。

    主键 `subject` 是**来源对象**（方块 ID / 实体 ID），不是表路径；表路径写在
    `value["table"]` 里，保留到源头的追溯。

    触发一次能拿到的量不依赖维度或群系，所以 `scope_level="global"`。
    带不带工具结果相同的表只写一行（`condition=""`），不写两行同样的数。
    """
    rows: list[WorldStat] = []
    report: dict = {"rows": 0, "by_trigger": {}, "unsupported_tables": {}, "skipped": 0}
    # 先攒后写：主键里没有 `trigger`，同一个 `(subject, condition)` 可能来自两张表
    # （`entities/sheep` 击杀与 `shearing/sheep` 剪毛都映射到 `minecraft:sheep`），
    # 边遍历边 `replace` 会让字母序在后的那张把前一张整条覆盖。所以第一阶段只
    # 收集，第二阶段先数哪些 `(subject, condition)` 撞车，只给撞车的那几行在
    # `condition` 里补上 `|trigger=...` 作为区分，其余行保持原格式。
    staged: list[tuple[str, str, dict]] = []

    for table_id in tables.ids():
        namespace, _, rest = table_id.partition(":")
        prefix, _, name = rest.partition("/")
        trigger = TRIGGER_BY_PREFIX.get(prefix)
        if trigger is None or not name:
            continue
        if table_id in skip:
            report["skipped"] += 1
            continue

        subject = (
            f"{namespace}:{name}"
            if trigger in SUBJECT_FROM_NAME and prefix not in KEEP_TABLE_PATH
            else table_id
        )
        results = [
            (condition, expect(table_id, tables, tool_probability=probability, tags=tags))
            for condition, probability in TOOL_VARIANTS
        ]
        present = results[0][1]
        absent = results[1][1]
        same = present.per_item == absent.per_item
        chosen = [(CONDITION_TOOLS_PRESENT, present)] if same else results

        for condition, result in chosen:
            value: dict = {
                "per_trigger_expected": {
                    item_id: round(amount, 4)
                    for item_id, amount in sorted(result.per_item.items())
                    if amount
                },
                "trigger": trigger,
                "table": table_id,
            }
            spreads = _cv_map(result)
            if spreads:
                value["per_trigger_cv"] = spreads
            if result.assumptions:
                value["assumptions"] = list(result.assumptions)
            if result.unsupported:
                value["unsupported"] = list(result.unsupported)
            staged.append((subject, condition, value))
            report["rows"] += 1
            report["by_trigger"][trigger] = report["by_trigger"].get(trigger, 0) + 1
            if result.unsupported:
                report["unsupported_tables"][table_id] = result.unsupported

    collisions = Counter((subject, condition) for subject, condition, _ in staged)
    for subject, condition, value in staged:
        tag = condition
        if collisions[(subject, condition)] > 1:
            tag = f"{condition}|trigger={value['trigger']}"
        rows.append(
            WorldStat(
                pack_version=pack_version,
                scope_level="global",
                dimension="",
                biome="",
                stat_type="loot_expectation",
                subject=subject,
                condition=tag,
                value=value,
                sample_size=0,
                confidence="high" if condition == CONDITION_TOOLS_PRESENT else "medium",
                derived_from=("rolls", "weight", "set_count", "condition"),
                provenance=provenance,
                note=(
                    f"{value['trigger']} 一次的期望产出（按表计）；"
                    "工具条件见 condition，附魔按无附魔级"
                ),
            )
        )

    return rows, report


def _frequency(density: dict) -> float | None:
    """结构频率：每区块的结构数。由间距（区块）换算。"""
    spacing = density.get("spacing")
    if not isinstance(spacing, (int, float)) or spacing <= 0:
        return None
    return round(1.0 / (float(spacing) ** 2), 6)


def merge_into(store, rows: list[WorldStat]) -> int:
    """把新行并入已有统计集合，同主键覆盖。返回写入条数。"""
    for row in rows:
        store.replace(row)
    return len(rows)


def density_lookup(store) -> dict[str, dict]:
    """从已有统计里取 `structure_density` 的 value，按结构集合索引。"""
    out: dict[str, dict] = {}
    for row in store.rows.values():
        if row.stat_type != "structure_density":
            continue
        out[row.subject] = dict(row.value)
    return out
