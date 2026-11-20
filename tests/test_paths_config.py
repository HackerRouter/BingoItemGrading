"""`config.yml` 的解析与必填校验：只有两个上游目录，错就报错。

后半部分专门锁 YAML 语义——这是引入 PyYAML 换来的东西，必须可验证：
注释、引号、`#` 在值里、以及**标量不被类型推断**。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bingo_grading import config, paths

TEMPLATE = """\
# 两个上游项目的位置
paths:
  recipe_analysis: '{base}/RecipeAnalysis'   # RA 根
  collector: '{base}/WorldGenStatsCollector'
"""


def _text(base: Path) -> str:
    return TEMPLATE.format(base=base.as_posix())


def _write(tmp_path: Path, text: str) -> Path:
    target = tmp_path / "config.yml"
    target.write_text(text, encoding="utf-8")
    return target


# ------------------------------------------------------------------ 基本行为


def test_load_accepts_full_config(tmp_path: Path) -> None:
    roots = config.load(_write(tmp_path, _text(tmp_path)))
    assert set(roots) == {"recipe_analysis", "collector"}
    assert roots["recipe_analysis"] == tmp_path / "RecipeAnalysis"


def test_load_resolves_relative_to_config_file(tmp_path: Path) -> None:
    roots = config.load(_write(tmp_path, TEMPLATE.format(base="rel")))
    assert roots["collector"] == tmp_path / "rel" / "WorldGenStatsCollector"


def test_load_collapses_dotdot(tmp_path: Path) -> None:
    roots = config.load(_write(tmp_path, TEMPLATE.format(base="../shared")))
    assert roots["collector"] == tmp_path.parent / "shared" / "WorldGenStatsCollector"


def test_missing_keys_are_listed(tmp_path: Path) -> None:
    text = "\n".join(
        line
        for line in _text(tmp_path).splitlines()
        if "collector:" not in line
    )
    with pytest.raises(config.ConfigError) as excinfo:
        config.load(_write(tmp_path, text))
    message = str(excinfo.value)
    assert "collector" in message
    assert "没有默认值" in message


def test_empty_value_is_rejected(tmp_path: Path) -> None:
    text = "\n".join(
        line
        for line in _text(tmp_path).splitlines()
        if "collector:" not in line
    )
    text += "\n  collector:\n"
    with pytest.raises(config.ConfigError) as excinfo:
        config.load(_write(tmp_path, text))
    assert "collector" in str(excinfo.value)


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    """本仓库自己的目录不再可配：写进去要报错，而不是悄悄生效。"""
    text = _text(tmp_path) + f"  stats: '{tmp_path.as_posix()}/stats'\n"
    with pytest.raises(config.ConfigError) as excinfo:
        config.load(_write(tmp_path, text))
    assert "stats" in str(excinfo.value)


def test_non_paths_top_level_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(config.ConfigError) as excinfo:
        config.load(_write(tmp_path, "roots:\n  collector: /tmp\n"))
    assert "roots" in str(excinfo.value)


def test_missing_file_reports_how_to_fix(tmp_path: Path) -> None:
    with pytest.raises(config.ConfigError) as excinfo:
        config.load(tmp_path / "nope.yml")
    assert "config.example.yml" in str(excinfo.value)


def test_find_config_prefers_environment(tmp_path: Path, monkeypatch) -> None:
    target = _write(tmp_path, _text(tmp_path))
    monkeypatch.setenv(config.CONFIG_ENV, str(target))
    assert config.find_config() == target


# ------------------------------------------------------------------ YAML 语义


def test_comments_are_supported(tmp_path: Path) -> None:
    """行内注释与全文注释都被忽略——这是 `.yml` 后缀应有的承诺。"""
    roots = config.load(_write(tmp_path, _text(tmp_path)))
    assert roots["recipe_analysis"] == tmp_path / "RecipeAnalysis"


def test_scalars_are_never_type_inferred(tmp_path: Path) -> None:
    """`26.3` / `on` / `no` / `0x10` 都必须原样是字符串。

    默认 SafeLoader 会把它们变成 float / bool / bool / int，路径就废了。
    """
    text = (
        "paths:\n"
        "  recipe_analysis: 26.3\n"
        "  collector: on\n"
    )
    roots = config.load(_write(tmp_path, text))
    assert roots["recipe_analysis"] == tmp_path / "26.3"
    assert roots["collector"] == tmp_path / "on"


def test_quoted_and_bare_values_are_equivalent(tmp_path: Path) -> None:
    quoted = "paths:\n  recipe_analysis: '../x'\n  collector: \"../y\"\n"
    bare = "paths:\n  recipe_analysis: ../x\n  collector: ../y\n"
    assert config.load(_write(tmp_path, quoted)) == config.load(
        _write(tmp_path, bare)
    )


def test_hash_inside_quotes_survives(tmp_path: Path) -> None:
    """值里的 `#` 加引号才安全，这是 YAML 标准行为，不是我们的方言。"""
    text = "paths:\n  recipe_analysis: 'a#b'\n  collector: 'c'\n"
    assert config.load(_write(tmp_path, text))["recipe_analysis"] == tmp_path / "a#b"


def test_yaml_syntax_error_is_reported(tmp_path: Path) -> None:
    with pytest.raises(config.ConfigError) as excinfo:
        config.load(_write(tmp_path, "paths: [\n"))
    assert "YAML" in str(excinfo.value)


def test_empty_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(config.ConfigError) as excinfo:
        config.load(_write(tmp_path, "# 只有注释\n"))
    assert "空" in str(excinfo.value)


def test_paths_must_be_a_mapping(tmp_path: Path) -> None:
    with pytest.raises(config.ConfigError) as excinfo:
        config.load(_write(tmp_path, "paths:\n  - a\n"))
    assert "paths" in str(excinfo.value)


# ------------------------------------------------------------------ 与 paths 的联动


def test_upstream_attributes_read_the_config(tmp_path: Path, monkeypatch) -> None:
    """`paths.REF_*` 是懒加载的，读到的是配置文件里的值。"""
    target = _write(tmp_path, _text(tmp_path))
    monkeypatch.setenv(config.CONFIG_ENV, str(target))
    paths.clear_cache()
    try:
        assert paths.REF_RECIPE_ANALYSIS == tmp_path / "RecipeAnalysis"
        assert paths.REF_COLLECTOR == tmp_path / "WorldGenStatsCollector"
        assert set(paths.roots()) == {"recipe_analysis", "collector"}
    finally:
        paths.clear_cache()


def test_project_roots_are_fixed_constants() -> None:
    """本仓库目录不走配置：它们是模块常量，`bg config` 里列在 fixed 下。"""
    assert paths.STATS_ROOT == paths.ROOT / "data" / "stats"
    assert paths.BUILD_ROOT == paths.ROOT / "build"
    assert set(paths.FIXED_ROOTS) == {
        "data",
        "upstream",
        "stats",
        "build",
        "knowledge",
    }
