"""结构模板的方块网格与形状匹配。

`facts/template.jsonl` 只导出「每个模板有多少块某方块」的计数，没有坐标。
所以凡是**形状**有关的问题（这里：下界门的门框缺几块）都必须读模板原件。
原版模板在 `data/upstream/<pack>/datapack/data/minecraft/structure/**/*.snbt`，
由 `bg data sync` 从上游解包结果复制而来。

一个模板的 `data` 字段是 `[{pos: [x, y, z], state: "minecraft:obsidian"}]`，
已经展开过 palettte，所以这里不需要再查调色板。

## 门框为什么不能只数黑曜石

废弃传送门的黑曜石是**散乱**的：`portal_1` 只剩 11 块，`giant_portal_1` 有 31 块，
而一个能点着的下界门最少要 **10 块**：内部 2×3 的空腔加上**上下各 2 块横梁、
左右各 3 块立柱**。四角是**不需要**的——这是最小门只要 10 块而不是 14 块的原因，
所以这里不能把 4×5 的外圈整圈算成需求。

```
. # # .     上横梁 2
# . . #     左右立柱各 3
# . . #
# . . #
. # # .     下横梁 2
```

所以不能直接数总数，得在模板里找「最像门框的那一块窗口」，再数缺口。

哭泣黑曜石（`minecraft:crying_obsidian`）**不能**当门框用，所以它出现在必需位上
只算缺口，不算已有——这正是要区分 `base(pos) == "minecraft:obsidian"` 的原因。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from mcshared.snbt import SnbtError, parse_snbt

from .gamedata import (
    PORTAL_FRAME_HEIGHT,
    PORTAL_FRAME_WIDTH,
    PORTAL_INNER_HEIGHT,
    PORTAL_INNER_WIDTH,
)

OBSIDIAN = "minecraft:obsidian"
CRYING_OBSIDIAN = "minecraft:crying_obsidian"
# 内腔可以站着走进去的方块。
PASSABLE = frozenset(
    {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
)


class TemplateError(ValueError):
    """模板文件不可用（缺字段、结构损坏）。"""


def _ring() -> tuple[tuple[int, int], ...]:
    """框架必需的 10 个格子（相对坐标）：上下横梁各 2、左右立柱各 3。

    四角**不在**里面——原版判定不要求四角有方块，所以这里也不该要求。
    """
    cells: list[tuple[int, int]] = []
    for du in range(1, PORTAL_INNER_WIDTH + 1):
        cells.append((du, 0))
        cells.append((du, PORTAL_INNER_HEIGHT + 1))
    for dv in range(1, PORTAL_INNER_HEIGHT + 1):
        cells.append((0, dv))
        cells.append((PORTAL_INNER_WIDTH + 1, dv))
    return tuple(cells)


def _inner() -> tuple[tuple[int, int], ...]:
    """内腔 6 个格子（相对坐标）。"""
    return tuple(
        (du, dv)
        for du in range(1, PORTAL_INNER_WIDTH + 1)
        for dv in range(1, PORTAL_INNER_HEIGHT + 1)
    )


FRAME_RING = _ring()
FRAME_INNER = _inner()

# 两个朝向：（u 轴, v 轴, 法线轴）。门只可能是轴对齐的，所以两种就够。
ORIENTATIONS = ((0, 1, 2), (2, 1, 0))
AXIS_NAMES = ("x", "y", "z")


@dataclass(frozen=True)
class BlockGrid:
    """一个结构模板的全部方块。坐标缺项按空气处理。"""

    template: str
    size: tuple[int, int, int]
    blocks: dict[tuple[int, int, int], str]

    def at(self, pos: tuple[int, int, int]) -> str:
        return self.blocks.get(pos, "minecraft:air")

    def base(self, pos: tuple[int, int, int]) -> str:
        """去掉方块状态，只留 ID。"""
        return self.at(pos).split("{", 1)[0]

    def count(self, block: str) -> int:
        return sum(1 for name in self.blocks.values() if name.split("{", 1)[0] == block)

    def block_counts(self) -> Counter:
        return Counter(name.split("{", 1)[0] for name in self.blocks.values())

    def as_dict(self) -> dict:
        return {
            "template": self.template,
            "size": list(self.size),
            "blocks": len(self.blocks),
        }


def load_template(path: Path, *, template_id: str | None = None) -> BlockGrid:
    """读一个 SNBT 模板。"""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise TemplateError(f"模板不存在：{path}") from exc
    try:
        doc = parse_snbt(text)
    except SnbtError as exc:
        raise TemplateError(f"{path} 不是合法 SNBT：{exc}") from exc
    if not isinstance(doc, dict):
        raise TemplateError(f"{path} 顶层不是复合标签")
    size = doc.get("size")
    if not isinstance(size, list) or len(size) != 3:
        raise TemplateError(f"{path} 缺 size 或形状不对")
    grid: dict[tuple[int, int, int], str] = {}
    for entry in doc.get("data") or []:
        if not isinstance(entry, dict):
            raise TemplateError(f"{path} 的 data 条目不是复合标签")
        pos = entry.get("pos")
        state = entry.get("state")
        if not isinstance(pos, list) or len(pos) != 3 or not isinstance(state, str):
            raise TemplateError(f"{path} 的 data 条目缺 pos/state")
        grid[(int(pos[0]), int(pos[1]), int(pos[2]))] = state
    return BlockGrid(
        template=template_id or path.stem,
        size=(int(size[0]), int(size[1]), int(size[2])),
        blocks=grid,
    )


def load_templates(directory: Path) -> dict[str, BlockGrid]:
    """读一个目录下所有模板，键是相对路径去掉后缀。"""
    directory = Path(directory)
    if not directory.is_dir():
        raise TemplateError(f"模板目录不存在：{directory}")
    out: dict[str, BlockGrid] = {}
    for path in sorted(directory.rglob("*.snbt")):
        rel = path.relative_to(directory).with_suffix("")
        key = rel.as_posix()
        out[key] = load_template(path, template_id=key)
    return out


@dataclass(frozen=True)
class FrameMatch:
    """一个模板里「最像下界门框」的那块窗口。"""

    template: str
    have: int
    missing: int
    inner_open: int
    axis: str
    origin: tuple[int, int, int]
    crying: int = 0

    @property
    def complete(self) -> bool:
        return self.missing == 0

    def as_dict(self) -> dict:
        return {
            "template": self.template,
            "have": self.have,
            "missing": self.missing,
            "inner_open": self.inner_open,
            "axis": self.axis,
            "origin": list(self.origin),
            "crying": self.crying,
        }


def match_portal_frame(
    grid: BlockGrid,
    *,
    min_open: int = 4,
) -> FrameMatch | None:
    """找最像下界门框的 4×5 窗口（4×5 只是包住门的边界，四角不算需求）。

    评分依次看：必需位上已有黑曜石的数量（`have`）、内腔可站立的格数（`inner_open`）。
    `min_open` 是内腔的最低要求——如果窗口内部被实心填满，那不是门，是黑曜石堆，
    玩家站不进去，也就无从谈起「补几块」。内腔不达标的窗口直接不参与比较。

    哭泣黑曜石不计入 `have`：它能出现在必需位上，但那只是缺口。
    """
    best_cells: tuple[int, int] | None = None
    best_score: tuple[int, int] | None = None
    best_axis = "x"
    best_origin = (0, 0, 0)
    best_have = 0
    best_crying = 0

    for u_axis, v_axis, n_axis in ORIENTATIONS:
        size_u = grid.size[u_axis]
        size_v = grid.size[v_axis]
        size_n = grid.size[n_axis]
        if (
            size_u < PORTAL_FRAME_WIDTH
            or size_v < PORTAL_FRAME_HEIGHT
            or size_n < 1
        ):
            continue
        for layer in range(size_n):
            for u0 in range(size_u - PORTAL_FRAME_WIDTH + 1):
                for v0 in range(size_v - PORTAL_FRAME_HEIGHT + 1):
                    have = 0
                    crying = 0
                    inner_open = 0
                    for du, dv in FRAME_RING:
                        pos = _place(u_axis, v_axis, n_axis, u0 + du, v0 + dv, layer)
                        name = grid.base(pos)
                        if name == OBSIDIAN:
                            have += 1
                        elif name == CRYING_OBSIDIAN:
                            crying += 1
                    for du, dv in FRAME_INNER:
                        pos = _place(u_axis, v_axis, n_axis, u0 + du, v0 + dv, layer)
                        if grid.base(pos) in PASSABLE:
                            inner_open += 1
                    if inner_open < min_open:
                        continue
                    score = (have, inner_open)
                    if best_score is None or score > best_score:
                        best_score = score
                        best_cells = (u0, v0)
                        best_axis = AXIS_NAMES[u_axis] + AXIS_NAMES[v_axis]
                        best_origin = _place(
                            u_axis, v_axis, n_axis, u0, v0, layer
                        )
                        best_have = have
                        best_crying = crying

    if best_score is None or best_cells is None:
        return None
    return FrameMatch(
        template=grid.template,
        have=best_have,
        missing=len(FRAME_RING) - best_have,
        inner_open=best_score[1],
        axis=best_axis,
        origin=best_origin,
        crying=best_crying,
    )


def _place(
    u_axis: int, v_axis: int, n_axis: int, u: int, v: int, n: int
) -> tuple[int, int, int]:
    coords = [0, 0, 0]
    coords[u_axis] = u
    coords[v_axis] = v
    coords[n_axis] = n
    return (coords[0], coords[1], coords[2])
