"""测试引导：在 `bingo_grading` 被 import 之前准备好 `config.yml`。

上游项目目录没有默认值，缺配置会在第一次访问 `paths.REF_*` 时报错。测试不能
依赖开发者本机的配置，所以这里按顺序取：

1. 已有的 `BG_CONFIG` 环境变量（尊重开发者显式选择）；
2. 仓库根的 `config.yml`（若存在）；
3. 否则在临时目录生成一份占位配置——测试全部用 `tmp_path` 造假目录树，
   不读真实上游产物，因此占位路径不需要存在。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _placeholder() -> Path:
    values = {
        "recipe_analysis": ROOT / "_no_such_upstream_" / "RecipeAnalysis",
        "collector": ROOT / "_no_such_upstream_" / "WorldGenStatsCollector",
    }
    directory = Path(tempfile.mkdtemp(prefix="bg-test-config-"))
    target = directory / "config.yml"
    lines = ["paths:"] + [
        f"  {key}: {value.as_posix()}" for key, value in values.items()
    ]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def _bootstrap() -> None:
    if os.environ.get("BG_CONFIG"):
        return
    local = ROOT / "config.yml"
    os.environ["BG_CONFIG"] = str(local if local.exists() else _placeholder())


_bootstrap()

