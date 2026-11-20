"""上游配方事实（RecipeAnalysis 的 `facts/recipe.jsonl`）→ 下游需要的折算视图。

**结构解释全在共享层**：`payload → RecipeIR` 由 `mcshared.recipe_ir` 完成，
槽位识别由 `mcshared.recipe_slots` 完成（按形状递归找 `{items,tags}`，天然覆盖
`extra` 里的具名槽位）。本模块只把 IR 翻译成「产出 / 用量 / 设备」，不自己
解释 payload 的形状——这是「解析不可再漏」的分工。

`station`（工艺设备）来自 RA 的知识表 `serializer_station.json`，由
`paths.serializer_stations` 解析、`bg data sync` 本地化。
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from mcshared.recipe_ir import RecipeIR

from bingo_grading.tags import TagSet, load as load_tags


class RecipeFactError(ValueError):
    """配方事实文件不可用。"""


@dataclass(frozen=True, eq=False)
class Recipe:
    """一条配方在下游视角下的样子。结构本身由 `RecipeIR` 持有。"""

    output: str
    count: float
    inputs: tuple[tuple[str, float], ...]
    candidates: tuple[tuple[str, ...], ...]
    slot_qty: tuple[float, ...]
    serializer: str
    station: str | None
    source_file: str
    ir: RecipeIR
    # 原料槽展开后一个物品都拿不到（tag 缺失，或配方本身没有原料）
    no_ingredient: bool = False
    # 展开失败的槽位原始写法（如 `#minecraft:planks`）
    unresolved: tuple[str, ...] = ()

    @classmethod
    def from_ir(
        cls,
        ir: RecipeIR,
        *,
        source_file: str = "",
        tags: TagSet | None = None,
    ) -> "Recipe | None":
        if ir.result_id is None or ir.result_count <= 0:
            return None
        counts: dict[str, float] = {}
        candidates: list[tuple[str, ...]] = []
        slot_qty: list[float] = []
        unresolved: list[str] = []
        for slot in ir.slots:
            choices = _resolve_choices(slot.choices, tags)
            if not choices:
                unresolved.append(",".join(slot.choices))
                continue
            candidates.append(choices)
            slot_qty.append(slot.qty)
            # 这里只给一个结构默认代表（候选第一个）。多候选槽的最终选择由
            # 成本模型做：`case/tools.py` 按合成链代价比较，不用结构启发式
            # （`#logs` 里的 `oak_wood` 有四合三的额外一步，绝不能优先选它）。
            name = choices[0]
            counts[name] = counts.get(name, 0.0) + slot.qty
        return cls(
            output=ir.result_id,
            count=ir.result_count,
            inputs=tuple(sorted(counts.items())),
            candidates=tuple(candidates),
            slot_qty=tuple(slot_qty),
            serializer=ir.serializer,
            station=ir.station,
            source_file=source_file,
            ir=ir,
            no_ingredient=not counts,
            unresolved=tuple(unresolved),
        )

    def amount_of(self, item: str) -> float:
        """配方里某个物品的总用量（按展开后的候选匹配，含 tag 成员）。"""
        return float(
            sum(
                qty
                for choices, qty in zip(self.candidates, self.slot_qty)
                if item in choices
            )
        )

    def as_dict(self) -> dict:
        return {
            "output": self.output,
            "count": self.count,
            "inputs": dict(self.inputs),
            "candidates": [list(choices) for choices in self.candidates],
            "serializer": self.serializer,
            "station": self.station,
            "file": self.source_file,
            "no_ingredient": self.no_ingredient,
            "unresolved": list(self.unresolved),
            "unparsed": list(self.ir.unparsed),
        }


def _resolve_choices(choices: tuple[str, ...], tags: TagSet | None) -> tuple[str, ...]:
    """槽位候选：`#tag` 展开成成员，精确物品原样保留，去重保序。

    标签展开复用 `bingo_grading.tags`（读 `facts/tag.jsonl`，递归展开 + 环检测），
    与 RA 的 `TagMembers` 行为一致。
    """
    out: list[str] = []
    for choice in choices:
        if choice.startswith("#"):
            if tags is None:
                continue
            out.extend(tags.expand(choice[1:], registry="minecraft:item"))
        else:
            out.append(choice)
    return tuple(dict.fromkeys(out))


@dataclass(frozen=True)
class Conversion:
    """一条配方在某个目标物品视角下的完整折算。

    正向（按配方合成）：

        `yields` 个 `output` ← `inputs`

    反向（把成品拆开，用于「1 干草块 → 9 小麦」这类逆折算）：
    `reverse=True`，此时 `yields` 是原配方里该物品的用量，`inputs` 是成品本身。
    """

    output: str
    yields: float
    inputs: tuple[tuple[str, float], ...]
    serializer: str
    source_file: str
    reverse: bool = False
    station: str | None = None
    candidates: tuple[tuple[str, ...], ...] = ()
    slot_qty: tuple[float, ...] = ()

    def amount_of(self, item: str) -> float | None:
        return dict(self.inputs).get(item)

    @property
    def detail(self) -> str:
        inputs = "、".join(f"{amount:g}×{name}" for name, amount in self.inputs)
        suffix = "，拆解" if self.reverse else ""
        return (
            f"{inputs} → {self.yields:g}×{self.output}"
            f"（{self.serializer or 'recipe'}{suffix}；{self.source_file}）"
        )

    def as_dict(self) -> dict:
        return {
            "output": self.output,
            "yields": self.yields,
            "inputs": dict(self.inputs),
            "serializer": self.serializer,
            "file": self.source_file,
            "reverse": self.reverse,
        }


class RecipeIndex:
    """按产出物品索引的配方集合。"""

    def __init__(
        self,
        by_output: dict[str, tuple[Recipe, ...]],
        *,
        unparsed: Counter | None = None,
        skipped: int = 0,
        partial: int = 0,
        no_ingredient: int = 0,
    ) -> None:
        self._by_output = by_output
        # payload 里没被 IR 解释的键 → 次数。正常应为空；非空说明上游加了字段。
        self.unparsed = unparsed or Counter()
        self.skipped = skipped
        self.partial = partial
        # 原料展开后为空的配方数（tag 缺失，或配方本来就没有原料）
        self.no_ingredient = no_ingredient

    def __len__(self) -> int:
        return sum(len(items) for items in self._by_output.values())

    def outputs(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_output))

    def for_output(self, output: str) -> tuple[Recipe, ...]:
        return self._by_output.get(output, ())

    def ratio(
        self, output: str, ingredient: str, *, serializer: str | None = None
    ) -> float | None:
        """每 1 个 `ingredient` 能做出几个 `output`。

        匹配走 IR 的全部候选（`coal` / `charcoal` 这类多选槽都算），
        不是只看成本模型挑中的那一个。
        """
        best: float | None = None
        for recipe in self._by_output.get(output, ()):
            if serializer and not recipe.serializer.startswith(serializer):
                continue
            amount = recipe.amount_of(ingredient)
            if amount <= 0:
                continue
            value = recipe.count / amount
            if best is None or value > best:
                best = value
        return best

    def recipe_for(
        self, output: str, ingredient: str, *, serializer: str | None = None
    ) -> Recipe | None:
        for recipe in self._by_output.get(output, ()):
            if serializer and not recipe.serializer.startswith(serializer):
                continue
            if recipe.amount_of(ingredient) > 0:
                return recipe
        return None

    def conversion(
        self,
        output: str,
        *,
        via: str | None = None,
        reverse: bool = False,
        serializer: str | None = None,
    ) -> Conversion | None:
        """取一条可用的完整折算（产出 + 各原料用量 + 设备）。

        - 正向：`output` 是配方产出。`via` 指定必须用到的原料，用来在多条
          配方（熔炼 / 合成 / 拆块）里挑一条。
        - 反向：`output` 是配方**原料**。`via` 指定被拆的成品物品。
        找不到时返回 `None`，调用方必须让相关路线缺席。
        """
        if reverse:
            for name, recipes in self._by_output.items():
                if via is not None and name != via:
                    continue
                for recipe in recipes:
                    if serializer and not recipe.serializer.startswith(serializer):
                        continue
                    amount = recipe.amount_of(output)
                    if amount <= 0:
                        continue
                    return Conversion(
                        output=output,
                        yields=amount,
                        inputs=((name, recipe.count),),
                        serializer=recipe.serializer,
                        source_file=recipe.source_file,
                        reverse=True,
                        station=recipe.station,
                    )
            return None
        for recipe in self._by_output.get(output, ()):
            if serializer and not recipe.serializer.startswith(serializer):
                continue
            if recipe.no_ingredient:
                continue
            if via is not None and recipe.amount_of(via) <= 0:
                continue
            return _forward(recipe)
        return None

    def conversions(
        self, output: str, *, serializer: str | None = None
    ) -> tuple[Conversion, ...]:
        """同一产出的**全部**正向折算。

        一个物品可能有多条配方（铁锭：熔炼矿石 / 爆烤矿石 / 拆铁块 / 拆粒），
        选哪一条要按成本比，不能只取第一条。
        """
        out: list[Conversion] = []
        for recipe in self._by_output.get(output, ()):
            if serializer and not recipe.serializer.startswith(serializer):
                continue
            if recipe.no_ingredient:
                continue
            out.append(_forward(recipe))
        return tuple(out)


def _forward(recipe: Recipe) -> Conversion:
    """一条配方 → 完整折算（产出 + 各槽用量 + 候选全集 + 设备）。"""
    return Conversion(
        output=recipe.output,
        yields=recipe.count,
        inputs=recipe.inputs,
        serializer=recipe.serializer,
        source_file=recipe.source_file,
        station=recipe.station,
        candidates=recipe.candidates,
        slot_qty=recipe.slot_qty,
    )


def _load_stations(path: str | None) -> dict[str, str | None]:
    """读 RA 的 `serializer_station.json`。缺文件就返回空表（station 全为 None）。"""
    if not path:
        return {}
    target = Path(path)
    if not target.is_file():
        return {}
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RecipeFactError(f"{target} 不是合法 JSON：{exc}") from exc
    return {
        key: value
        for key, value in doc.items()
        if not key.startswith("_") and (value is None or isinstance(value, str))
    }


def _load_tag_set(path: str | None) -> TagSet | None:
    """读 `facts/tag.jsonl`。缺文件时返回 None（tag 槽位展开失败会被记进 unresolved）。"""
    if not path:
        return None
    target = Path(path)
    if not target.is_file():
        return None
    return load_tags(target)


@lru_cache(maxsize=8)
def load(
    path: str,
    station_path: str | None = None,
    tag_path: str | None = None,
) -> RecipeIndex:
    """读上游 `facts/recipe.jsonl`，逐行反序列化成 IR，并展开 tag 原料。

    多候选槽只保留候选全集（`Recipe.candidates`）；选哪一个由成本模型决定，
    不在这里用「有没有配方」这类结构启发式预选。

    `partial` 也解析（只是缺个别槽位），`failed` 计入 `skipped`；
    `inputs` 为空的配方标 `no_ingredient`（不静默当成「白送」）。
    """
    target = Path(path)
    if not target.is_file():
        raise RecipeFactError(f"找不到配方事实：{target}")
    stations = _load_stations(station_path)
    tags = _load_tag_set(tag_path)
    unparsed: Counter = Counter()
    skipped = 0
    partial = 0
    parsed: list[tuple[RecipeIR, str]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RecipeFactError(f"{target} 不是合法 JSONL：{exc}") from exc
        if row.get("kind") != "recipe":
            continue
        status = row.get("status")
        if status == "failed":
            skipped += 1
            continue
        if status == "partial":
            partial += 1
        payload = row.get("payload") or {}
        serializer = payload.get("serializer")
        try:
            ir = RecipeIR.from_payload(
                payload,
                station=stations.get(serializer) if isinstance(serializer, str) else None,
            )
        except ValueError:
            skipped += 1
            continue
        unparsed.update(ir.unparsed)
        provenance = row.get("prov") or {}
        parsed.append((ir, str(provenance.get("file") or "")))

    outputs = frozenset(ir.result_id for ir, _ in parsed if ir.result_id)
    by_output: dict[str, list[Recipe]] = {}
    no_ingredient = 0
    for ir, source_file in parsed:
        recipe = Recipe.from_ir(ir, source_file=source_file, tags=tags)
        if recipe is None:
            skipped += 1
            continue
        if recipe.no_ingredient:
            no_ingredient += 1
        by_output.setdefault(recipe.output, []).append(recipe)
    if not by_output:
        raise RecipeFactError(f"{target} 里没有可用的配方行")
    return RecipeIndex(
        {name: tuple(items) for name, items in by_output.items()},
        unparsed=unparsed,
        skipped=skipped,
        partial=partial,
        no_ingredient=no_ingredient,
    )
