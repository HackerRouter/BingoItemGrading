"""两个上游项目的位置：`config.yml`。

本仓库自己的目录（`data/`、`build/` 及其各棵子树）固定在 `paths.py` 的
常量区，不参与配置——它们就是仓库的一部分，可配只会让「读的是哪份数据」
变成未知数。真正因机器而异只有一件事：两个上游项目克隆在哪。

没有默认值。缺文件、缺项、空值、未知项，一律在**读配置时**报错并中止。

## 为什么用真 YAML，而不是自写一个子集

配置文件是给维护者手改的，`.yml` 后缀就是一份承诺：能写注释、能换行、
值里的 `#` 不是注释的一部分。与其自写一个「像 YAML 但不是」的方言
（写错了能读进去但不报错），不如直接用 PyYAML。

唯一的代价是隐式类型推断：`26.3` 会变 float、`on`/`yes` 变 bool、`1:20`
变 60。对路径来说这是纯粹的雷，所以 `_PathLoader` 把所有标量都读成字符串
（清空 `yaml_implicit_resolvers`）。这一条**不依赖**模板里的引号——即使有人
裸写 `recipe_analysis: 26.3`，拿到的也是字符串 `"26.3"`。
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

CONFIG_NAME = "config.yml"
CONFIG_ENV = "BG_CONFIG"

# 必须全部给出，顺序只用于报错时好听。
REQUIRED = (
    "recipe_analysis",
    "collector",
)

TOP_LEVEL = "paths"


class ConfigError(ValueError):
    """配置缺失或不合法。调用方应当报错退出，不要退化到默认值。"""


class _PathLoader(yaml.SafeLoader):
    """标量一律按字符串读的 SafeLoader。

    清空 `yaml_implicit_resolvers` 后，`26.3` / `on` / `null` / `0x10` 都不再
    被转成 float / bool / None / int，全部原样是 `str`。配置里没有一个值需要
    类型推断，路径尤其如此。
    """


_PathLoader.yaml_implicit_resolvers = {}


def find_config() -> Path | None:
    """当前生效的配置文件：`BG_CONFIG` → 当前目录 → 仓库根。"""
    env = os.environ.get(CONFIG_ENV)
    if env:
        return Path(env).expanduser()
    root = Path(__file__).resolve().parents[2]
    for candidate in (Path.cwd() / CONFIG_NAME, root / CONFIG_NAME):
        if candidate.is_file():
            return candidate
    return None


def parse(text: str, source: Path) -> dict[str, str]:
    """解析 `paths:` 映射，返回**键 → 字符串值**（未做路径解析）。"""
    try:
        document = yaml.load(text, Loader=_PathLoader)  # noqa: S506 - SafeLoader 子类
    except yaml.YAMLError as exc:
        raise ConfigError(f"{source} YAML 语法错误：\n{exc}") from exc

    if document is None:
        raise ConfigError(f"{source} 是空的（模板见 config.example.yml）")
    if not isinstance(document, dict):
        raise ConfigError(
            f"{source} 顶层必须是映射，实际是 {type(document).__name__}"
        )

    extra = sorted(str(key) for key in document if key != TOP_LEVEL)
    if extra:
        raise ConfigError(
            f"{source} 未知顶层键：{', '.join(extra)}（只认 `{TOP_LEVEL}:`）"
        )
    if TOP_LEVEL not in document:
        raise ConfigError(f"{source} 缺少 `{TOP_LEVEL}:` 顶层键")

    mapping = document[TOP_LEVEL]
    if not isinstance(mapping, dict):
        raise ConfigError(
            f"{source} `{TOP_LEVEL}:` 下面必须是映射，"
            f"实际是 {type(mapping).__name__}"
        )

    values: dict[str, str] = {}
    for key, value in mapping.items():
        name = str(key)
        if value is None:
            raise ConfigError(f"{source} `{TOP_LEVEL}.{name}` 的值为空")
        stripped = value.strip() if isinstance(value, str) else ""
        if not stripped:
            raise ConfigError(f"{source} `{TOP_LEVEL}.{name}` 的值为空")
        values[name] = stripped
    return values


def load(path: Path | None = None) -> dict[str, Path]:
    """读配置并校验完整性，返回**键 → 绝对路径**。任何问题都抛 `ConfigError`。"""
    file = path if path is not None else find_config()
    if file is None:
        raise ConfigError(
            f"找不到配置文件：设 `{CONFIG_ENV}`，或在当前目录/仓库根放 "
            f"`{CONFIG_NAME}`（模板见 `config.example.yml`）"
        )
    if not file.is_file():
        raise ConfigError(f"配置文件不存在：{file}（模板见 config.example.yml）")
    raw = parse(file.read_text(encoding="utf-8"), file)
    missing = [key for key in REQUIRED if key not in raw]
    if missing:
        raise ConfigError(
            f"{file} 缺少 {len(missing)} 项：{', '.join(missing)}"
            "（全部必填，没有默认值；模板见 config.example.yml）"
        )
    unknown = sorted(key for key in raw if key not in REQUIRED)
    if unknown:
        raise ConfigError(f"{file} 有未知配置项：{', '.join(unknown)}")

    base = file.parent
    roots: dict[str, Path] = {}
    for key in REQUIRED:
        candidate = Path(raw[key]).expanduser()
        resolved = candidate if candidate.is_absolute() else (base / candidate)
        # 只折叠 `..`，不 `resolve()`：上游目录常是 junction，解析链接会
        # 把路径拽到别的盘上，同步校验就会互相打架。
        roots[key] = Path(os.path.normpath(resolved))
    return roots
