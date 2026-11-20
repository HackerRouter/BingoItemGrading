"""游戏数据常量的一致性：同一件事只能有一个数。

`bingo_grading/gamedata.py` 是**唯一**的游戏数据入口。别的模块若必须重复它的数值
（例如 `templates.py` 用坐标集合描述门框形状），就在这里钉一条断言防漂移。
"""

from __future__ import annotations

from bingo_grading import gamedata, units
from bingo_grading.templates import FRAME_RING


def test_full_frame_matches_portal_ring() -> None:
    """门框块数只有一份真值：`templates.FRAME_RING` 的格子数。

    `gamedata.FULL_FRAME` 是成本口径里的同一个数（10 块）。改门框形状时两处
    必须一起变，否则「从零垒满」和「补缺口」的定价会静默失配。
    """
    assert len(FRAME_RING) == gamedata.FULL_FRAME


def test_patch_frame_is_between_nothing_and_full() -> None:
    """废弃传送门平均还缺几块：必须是正数，且小于从零垒满。"""
    assert 0 < gamedata.PATCH_FRAME < gamedata.FULL_FRAME


def test_cast_batch_is_positive_and_covers_a_plan() -> None:
    """一次浇铸的批量：正数，且至少够一扇门框（否则「一次浇铸」永远凑不齐门）。"""
    assert gamedata.CAST_BATCH > 0
    assert gamedata.CAST_BATCH >= gamedata.FULL_FRAME


def test_run_blocks_per_tu_matches_sprint_speed() -> None:
    """TU 的定义是时间，跑图格数是派生结论——两者必须自洽。

    `units.SECONDS_PER_TU` 秒 × `gamedata.SPRINT_BLOCKS_PER_SECOND` 格/秒，
    就是 1 TU 能跑的格数（3 位有效数字取整）。历史上这里是手写的 100，
    隐含 14.3 格/秒，比疾跑还快 2.55 倍，一直没人发现——这条断言就是为了
    下次改其中一个而忘了另一个时当场失败。
    """
    derived = units.SECONDS_PER_TU * gamedata.SPRINT_BLOCKS_PER_SECOND
    assert abs(units.RUN_BLOCKS_PER_TU - derived) / derived < 0.02
