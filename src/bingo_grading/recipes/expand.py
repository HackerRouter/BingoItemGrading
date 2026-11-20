"""合成表展开：配方链 → 非合成来源的叶子。

以某个物品为根，沿配方递归，直到「既没有配方、也没有非合成来源」的叶子。
记录合成链深度作为合成成本，但不直接当难度分。

反向合成（块分解）在数据里就是普通配方：铁块 → 铁锭。环上若无外部入口，
递归在环处自然终止，不会凭空造出一个槽位；环上有外部入口时，该入口的
来源照常出现在叶子里。这与上游 `cycle_no_entry` 的语义一致，只是这里
用递归本身表达，不单独维护 SCC。

tag 输入只取前若干个成员：槽位粒度问的是「是否存在」，取代表成员足够；
全量展开会让木板这类 tag 把几十个成员的全部来源拉进来。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..sources.graph import Graph
from ..sources.index import SourceRecord

RECIPE_FAMILY = "recipes"
MAX_DEPTH = 4
TAG_MEMBER_LIMIT = 6
MAX_LEAVES = 2000


@dataclass(frozen=True)
class Recipe:
    id: str
    output: str
    inputs: tuple[str, ...]
    station: str | None


@dataclass
class CraftIndex:
    recipes: dict[str, list[Recipe]] = field(default_factory=dict)
    members: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class Leaf:
    """一条落在非合成来源上的路径。"""

    item: str
    source: SourceRecord
    depth: int
    chain: tuple[str, ...]


@dataclass
class ExpandStats:
    cycles: set[str] = field(default_factory=set)
    truncated: int = 0
    missing: set[str] = field(default_factory=set)
    tag_limited: set[str] = field(default_factory=set)

    def as_dict(self) -> dict:
        return {
            "cycles": sorted(self.cycles),
            "truncated": self.truncated,
            "missing": sorted(self.missing)[:50],
            "missing_count": len(self.missing),
            "tag_limited": sorted(self.tag_limited),
        }


def build_index(graph: Graph) -> CraftIndex:
    index = CraftIndex()
    for rule in graph.rules:
        if rule.family != RECIPE_FAMILY:
            continue
        recipe = _recipe_of(rule)
        if recipe is not None:
            index.recipes.setdefault(recipe.output, []).append(recipe)

    index.members = _tag_members(graph)
    return index


def _tag_members(graph: Graph) -> dict[str, tuple[str, ...]]:
    """tag → 物品成员。嵌套 tag 递归展开。

    `wooden_tool_materials` 这类 tag 的成员是另一个 tag（`planks`），
    只看一层会把木剑这类配方判成「输入不可得」。
    """
    raw: dict[str, list[str]] = {}
    for rule in graph.rules:
        if not rule.head.startswith("tag:"):
            continue
        for node in rule.body:
            if node.startswith("item:") or node.startswith("tag:"):
                raw.setdefault(rule.head, []).append(node)

    def resolve(tag: str, seen: frozenset[str]) -> list[str]:
        out: list[str] = []
        for node in raw.get(tag, ()):
            if node.startswith("item:"):
                name = node.split(":", 1)[1]
                if name not in out:
                    out.append(name)
            elif node.startswith("tag:") and node not in seen:
                for member in resolve(node, seen | {node}):
                    if member not in out:
                        out.append(member)
        return out

    members: dict[str, tuple[str, ...]] = {}
    for tag in raw:
        resolved = resolve(tag, frozenset({tag}))
        if resolved:
            members[tag] = tuple(resolved)
    return members


def _recipe_of(rule) -> Recipe | None:
    output = rule.head
    if not output.startswith("item:"):
        return None
    inputs: list[str] = []
    station: str | None = None
    for node in rule.body:
        if node.startswith("item:") or node.startswith("tag:"):
            inputs.append(node)
        elif node.startswith("station:"):
            station = node
    if not inputs:
        return None
    return Recipe(
        id=rule.id,
        output=output.split(":", 1)[1],
        inputs=tuple(inputs),
        station=station,
    )


def direct_sources(records: list[SourceRecord]) -> dict[str, list[SourceRecord]]:
    table: dict[str, list[SourceRecord]] = {}
    for record in records:
        table.setdefault(record.item, []).append(record)
    return table


def expand(
    index: CraftIndex,
    direct: dict[str, list[SourceRecord]],
    root: str,
    *,
    max_depth: int = MAX_DEPTH,
    tag_limit: int = TAG_MEMBER_LIMIT,
    max_leaves: int = MAX_LEAVES,
) -> tuple[list[Leaf], ExpandStats]:
    """展开一个物品的全部配方路径，返回落在非合成来源上的叶子。

    配方是 AND：输入里只要有一条不可得，整条配方路径就不成立。
    没有这条规则，「铁锭 → 铁粒 → 铁镐 → 木棍」会把树叶当成铁锭的来源——
    铁镐本身要先有铁锭，这条链只是在绕圈。
    """

    leaves: list[Leaf] = []
    stats = ExpandStats()
    emitted = 0
    hit_limit = False

    def walk(item: str, depth: int, path: frozenset[str], chain: tuple[str, ...]) -> tuple[bool, list[Leaf]]:
        """返回 `(该物品是否可得, 该物品贡献的叶子)`。"""
        nonlocal emitted, hit_limit
        if item in path:
            stats.cycles.add(item)
            return False, []
        if emitted >= max_leaves:
            hit_limit = True
            # 配额耗尽后不再贡献叶子，但可得性照旧按直接来源判定：
            # 把后续分支一并判成不可得，会让先展开的大子树挤掉简单配方。
            return bool(direct.get(item)), []

        own = [Leaf(item=item, source=source, depth=depth, chain=chain) for source in direct.get(item, ())]
        emitted += len(own)
        valid = bool(own)
        found = list(own)

        recipes = index.recipes.get(item, ())
        if not recipes:
            if not own:
                stats.missing.add(item)
            return valid, found
        if depth >= max_depth:
            hit_limit = True
            return valid, found

        for recipe in recipes:
            recipe_ok = True
            recipe_leaves: list[Leaf] = []
            for ref in recipe.inputs:
                if ref.startswith("tag:"):
                    ok, sub = _walk_tag(ref, depth, path | {item}, chain + (recipe.id,))
                    if not ok:
                        recipe_ok = False
                    recipe_leaves.extend(sub)
                elif ref.startswith("item:"):
                    ok, sub = walk(ref.split(":", 1)[1], depth + 1, path | {item}, chain + (recipe.id,))
                    if not ok:
                        recipe_ok = False
                    recipe_leaves.extend(sub)
            if recipe_ok:
                valid = True
                found.extend(recipe_leaves)

        return valid, found

    def _walk_tag(
        tag: str, depth: int, path: frozenset[str], chain: tuple[str, ...]
    ) -> tuple[bool, list[Leaf]]:
        members = index.members.get(tag, ())
        if len(members) > tag_limit:
            stats.tag_limited.add(tag)
        ok_any = False
        found: list[Leaf] = []
        for member in members[:tag_limit]:
            ok, sub = walk(member, depth + 1, path, chain)
            if ok:
                ok_any = True
                found.extend(sub)
        return ok_any, found

    _, found = walk(root, 0, frozenset(), ())
    if hit_limit:
        stats.truncated = 1
    # 同一叶子可能从多条配方路径到达，按 (来源, 深度, 链) 去重。
    unique: dict[tuple[str, str, int, tuple[str, ...]], Leaf] = {}
    for leaf in found:
        unique.setdefault((leaf.item, leaf.source.rule_ref, leaf.depth, leaf.chain), leaf)
    return list(unique.values()), stats
