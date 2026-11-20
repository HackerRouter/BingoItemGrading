"""比对重构前后的期望产出是否逐项一致。

`expect.py` 改成读归一结构后，数值必须与旧的「直接解析原始 JSON」实现逐项相同。
本脚本把旧实现原样抄在这里，跑同一批表，比较 `per_item` / `total_items` / 诊断集合。

退出码 0 = 一致。输出写到 build/expect-parity.txt。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bingo_grading import paths  # noqa: E402
from bingo_grading.loot import expect as new_expect  # noqa: E402
from bingo_grading.loot.tables import load  # noqa: E402

MAX_DEPTH = 8
NO_ENCHANT_LEVEL = 0

# 本次重构**有意**改变的 3 张表：它们的嵌套条目把表内联在 `value` 里，
# 旧实现当成「未处理类型」丢掉了。除这 3 张外，数值必须逐项一致。
EXPECTED_NUMERIC = frozenset(
    {
        "minecraft:equipment/trial_chamber",
        "minecraft:equipment/trial_chamber_melee",
        "minecraft:equipment/trial_chamber_ranged",
    }
)

NEUTRAL_CONDITIONS = frozenset(
    {
        "minecraft:survives_explosion",
        "minecraft:killed_by_player",
        "minecraft:entity_properties",
        "minecraft:damage_source_properties",
        "minecraft:match_tool",
        "minecraft:location_check",
    }
)


class Ctx:
    def __init__(self, tool_probability=1.0):
        self.assumptions = set()
        self.unsupported = set()
        self.tool_probability = tool_probability
        if tool_probability >= 1.0:
            self.assumptions.add("工具条件按「玩家持有该工具」计为 1.0")
        elif tool_probability <= 0.0:
            self.assumptions.add("工具条件按「徒手」计为 0.0")

    def assume(self, text):
        self.assumptions.add(text)

    def skip(self, text):
        self.unsupported.add(text)


def number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, dict):
        return None
    kind = str(value.get("type") or "")
    if kind.endswith("uniform"):
        low = value.get("min_inclusive", value.get("min"))
        high = value.get("max_inclusive", value.get("max"))
        if isinstance(low, (int, float)) and isinstance(high, (int, float)):
            return (float(low) + float(high)) / 2
        return None
    if kind.endswith("binomial"):
        n, p = value.get("n"), value.get("p")
        if isinstance(n, (int, float)) and isinstance(p, (int, float)):
            return float(n) * float(p)
        return None
    if kind.endswith("constant"):
        raw = value.get("value")
        return float(raw) if isinstance(raw, (int, float)) else None
    return None


def conditions_of(node):
    out = []
    for key in ("condition", "conditions"):
        raw = node.get(key)
        if raw is None:
            continue
        nodes = raw if isinstance(raw, list) else [raw]
        for item in nodes:
            if isinstance(item, dict):
                out.append(item)
            elif isinstance(item, str):
                out.append({"condition": item})
    return out


def cond_type(node):
    return str(node.get("condition") or node.get("type") or "")


def as_node(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return {"condition": value}
    return {}


def condition_probability(node, ctx, depth=0):
    if depth > MAX_DEPTH:
        ctx.skip("条件嵌套过深")
        return 0.0
    kind = cond_type(node)
    if not kind:
        ctx.skip(f"条件无类型：{sorted(node)}")
        return 0.0
    if kind in ("minecraft:tool/can_silk_touch", "minecraft:tool/can_shear"):
        return ctx.tool_probability
    if kind in NEUTRAL_CONDITIONS:
        return 1.0
    if kind == "minecraft:random_chance":
        chance = node.get("chance")
        return float(chance) if isinstance(chance, (int, float)) else 0.0
    if kind in ("minecraft:table_bonus", "minecraft:random_chance_with_enchanted_bonus"):
        chances = node.get("chances")
        if isinstance(chances, list) and chances:
            value = chances[min(NO_ENCHANT_LEVEL, len(chances) - 1)]
            if isinstance(value, (int, float)):
                ctx.assume("附魔加成按无附魔级（chances[0]）计")
                return float(value)
        return 0.0
    if kind == "minecraft:inverted":
        inner = node.get("term")
        if isinstance(inner, dict):
            return 1.0 - condition_probability(inner, ctx, depth + 1)
        ctx.skip("inverted 缺 term")
        return 0.0
    if kind == "minecraft:any_of":
        terms = [t for t in node.get("terms") or [] if isinstance(t, (dict, str))]
        if not terms:
            return 0.0
        fail = 1.0
        for term in terms:
            fail *= 1.0 - condition_probability(as_node(term), ctx, depth + 1)
        return 1.0 - fail
    if kind == "minecraft:all_of":
        terms = [t for t in node.get("terms") or [] if isinstance(t, (dict, str))]
        if not terms:
            return 0.0
        product = 1.0
        for term in terms:
            product *= condition_probability(as_node(term), ctx, depth + 1)
        return product
    ctx.skip(f"条件类型未处理：{kind}")
    return 0.0


def conditions_probability(node, ctx):
    conditions = conditions_of(node)
    if not conditions:
        return 1.0
    product = 1.0
    for condition in conditions:
        product *= condition_probability(condition, ctx)
    return product


def expected_count(modifiers, ctx):
    count = 1.0
    for modifier in modifiers:
        kind = str(modifier.get("type") or modifier.get("function") or "")
        if kind == "minecraft:set_count":
            value = number(modifier.get("count"))
            if value is None:
                ctx.skip(f"set_count 的 count 无法解析：{modifier.get('count')!r}")
            else:
                count = value
        elif kind == "minecraft:limit_count":
            limit = modifier.get("limit") or {}
            high = number(limit)
            if kind and high is not None:
                count = min(count, high)
        elif kind in ("minecraft:explosion_decay", "minecraft:set_damage"):
            continue
        elif kind in ("minecraft:enchanted_count_increase", "minecraft:apply_bonus"):
            ctx.assume("不计附魔对数量的加成")
        elif kind in (
            "minecraft:enchant_randomly",
            "minecraft:enchant_with_levels",
            "minecraft:set_potion",
            "minecraft:set_name",
            "minecraft:set_enchantments",
            "minecraft:copy_components",
            "minecraft:copy_state",
            "minecraft:set_stew_effect",
            "minecraft:set_ominous_bottle_amplifier",
            "minecraft:exploration_map",
            "minecraft:filtered",
            "minecraft:furnace_smelt",
        ):
            continue
        else:
            ctx.skip(f"modifier 未处理：{kind}")
    return count


def entry_parts(entry):
    kind = str(entry.get("type") or "")
    name = entry.get("name")
    if not isinstance(name, str):
        name = entry.get("value")
    children = [c for c in (entry.get("children") or []) if isinstance(c, dict)]
    raw = entry.get("modifier")
    if raw is None:
        raw = entry.get("functions")
    nodes = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])
    return kind, name if isinstance(name, str) else None, children, [n for n in nodes if isinstance(n, dict)]


def weight(entry):
    value = entry.get("weight")
    return float(value) if isinstance(value, (int, float)) else 1.0


def add(target, item, amount):
    if amount:
        target[item] = target.get(item, 0.0) + amount


def old_entry(entry, share, ctx, tables, depth, apply_conditions=True):
    kind, name, children, modifiers = entry_parts(entry)
    out, total = {}, 0.0
    if depth > MAX_DEPTH:
        ctx.skip("嵌套表过深")
        return out, total
    if apply_conditions:
        share *= conditions_probability(entry, ctx)
        if share <= 0:
            return out, total
    if kind.endswith(":empty"):
        return out, total
    if kind.endswith(":item") and name:
        amount = share * expected_count(modifiers, ctx)
        add(out, name, amount)
        return out, total + amount
    if kind.endswith(":loot_table") and name:
        nested = tables.get(name)
        if nested is None:
            ctx.skip(f"嵌套表不存在：{name}")
            return out, total
        nested_out, nested_total = old_table(nested, ctx, tables, depth + 1)
        for item, value in nested_out.items():
            add(out, item, value * share)
        return out, nested_total * share
    if kind.endswith(":group") or kind.endswith(":sequence"):
        for child in children:
            child_out, child_total = old_entry(child, share, ctx, tables, depth + 1)
            for item, value in child_out.items():
                add(out, item, value)
            total += child_total
        return out, total
    if kind.endswith(":alternatives"):
        remaining = share
        for child in children:
            probability = conditions_probability(child, ctx)
            effective = remaining * probability
            if effective:
                child_out, child_total = old_entry(
                    child, effective, ctx, tables, depth + 1, apply_conditions=False
                )
                for item, value in child_out.items():
                    add(out, item, value)
                total += child_total
            remaining *= 1.0 - probability
            if remaining <= 0:
                break
        return out, total
    if kind.endswith(":tag"):
        ctx.skip(f"tag 条目未展开：{name}")
        return out, total
    if kind.endswith(":dynamic"):
        ctx.skip(f"dynamic 条目无法静态求值：{name}")
        return out, total
    ctx.skip(f"条目类型未处理：{kind}")
    return out, total


def old_table(doc, ctx, tables, depth=0):
    out, total = {}, 0.0
    for pool in doc.get("pools") or []:
        if not isinstance(pool, dict):
            continue
        rolls = number(pool.get("rolls"))
        if rolls is None:
            ctx.skip(f"rolls 无法解析：{pool.get('rolls')!r}")
            continue
        pool_probability = conditions_probability(pool, ctx)
        entries = [e for e in (pool.get("entries") or []) if isinstance(e, dict)]
        weights = sum(weight(e) for e in entries)
        if not entries or weights <= 0:
            continue
        for entry in entries:
            share = rolls * pool_probability * (weight(entry) / weights)
            entry_out, entry_total = old_entry(entry, share, ctx, tables, depth)
            for item, value in entry_out.items():
                add(out, item, value)
            total += entry_total
    return out, total


def main() -> int:
    resolved = paths.loot_tables("26.3")
    tables = load([resolved.path])
    raw: dict[str, dict] = {}
    # 原始 JSON 按 ID 索引，供旧实现使用
    from mcshared.loot import table_id_from_file  # noqa: E402

    base = resolved.path.parents[3]
    for path in sorted(resolved.path.rglob("*.json")):
        rel = path.relative_to(base).as_posix()
        raw[table_id_from_file(rel)] = json.loads(path.read_text(encoding="utf-8"))

    diffs: list[str] = []
    numeric = 0
    expected = 0
    checked = 0
    for table_id in tables.ids():
        for tool_probability in (1.0, 0.0):
            old_ctx = Ctx(tool_probability)
            old_out, old_total = old_table(raw[table_id], old_ctx, raw)
            new = new_expect.expect(table_id, tables, tool_probability=tool_probability)
            checked += 1
            changed = old_out != new.per_item or not math.isclose(
                old_total, new.total_items, rel_tol=1e-12, abs_tol=1e-12
            )
            if changed and table_id in EXPECTED_NUMERIC:
                expected += 1
            elif changed:
                numeric += 1
                diffs.append(
                    f"[数值] {table_id} tools={tool_probability}\n"
                    f"  old={dict(sorted(old_out.items()))} total={old_total}\n"
                    f"  new={dict(sorted(new.per_item.items()))} total={new.total_items}"
                )
            elif sorted(old_ctx.unsupported) != new.unsupported:
                diffs.append(
                    f"[诊断] {table_id} tools={tool_probability}\n"
                    f"  old: {sorted(old_ctx.unsupported)}\n  new: {new.unsupported}"
                )

    print(
        f"checked={checked} unexpected_numeric={numeric} "
        f"expected_numeric={expected} other_diffs={len(diffs)}"
    )
    if diffs:
        out = ROOT / "build" / "expect-parity.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n\n".join(diffs[:60]), encoding="utf-8")
        print(out)
    return 1 if numeric else 0


if __name__ == "__main__":
    raise SystemExit(main())
