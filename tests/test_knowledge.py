"""知识表加载与校验。"""

from __future__ import annotations

from pathlib import Path

import pytest

from bingo_grading import paths
from bingo_grading.sources.knowledge import (
    KnowledgeError,
    load_routes,
    load_structure_maps,
    probabilities_table,
)


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_structure_map_longest_prefix(tmp_path: Path) -> None:
    path = write(
        tmp_path / "s.toml",
        'underground_sets = ["minecraft:ancient_cities"]\n'
        "\n"
        "[loot_prefixes]\n"
        '"chests/ancient_city" = "minecraft:ancient_cities"\n'
        '"chests/" = "minecraft:other"\n',
    )
    maps = load_structure_maps(path)
    assert maps.set_for_table("minecraft:chests/ancient_city_ice_box") == "minecraft:ancient_cities"
    assert maps.set_for_table("minecraft:chests/whatever") == "minecraft:other"
    assert maps.underground_sets == frozenset({"minecraft:ancient_cities"})


def test_structure_map_rejects_namespaced_key(tmp_path: Path) -> None:
    path = write(
        tmp_path / "s.toml",
        '[loot_prefixes]\n"minecraft:chests/village/" = "minecraft:villages"\n',
    )
    with pytest.raises(KnowledgeError, match="不带命名空间"):
        load_structure_maps(path)


def test_structure_map_absent_file_is_empty(tmp_path: Path) -> None:
    maps = load_structure_maps(tmp_path / "absent.toml")
    assert maps.loot_prefixes == ()
    assert maps.set_for_table("minecraft:chests/village/village_temple") is None


def test_routes_reject_top_level_after_table(tmp_path: Path) -> None:
    path = write(
        tmp_path / "r.toml",
        "[dimension_keywords]\n"
        '"the_nether" = ["minecraft:nether_"]\n'
        "underground_blocks = []\n",
    )
    with pytest.raises(KnowledgeError, match="可疑的维度名"):
        load_routes(path)


def test_routes_reads_keywords_and_sets(tmp_path: Path) -> None:
    path = write(
        tmp_path / "r.toml",
        'underground_blocks = ["minecraft:redstone_ore"]\n'
        'underground_structure_sets = ["minecraft:mineshafts"]\n'
        "\n"
        "[dimension_keywords]\n"
        '"the_nether" = ["minecraft:nether_"]\n',
    )
    rules = load_routes(path)
    assert rules.is_underground_block("minecraft:redstone_ore")
    assert rules.other_dimension_of("minecraft:nether_quartz_ore") == "the_nether"
    assert rules.underground_structure_sets == frozenset({"minecraft:mineshafts"})


def test_repository_knowledge_files_load() -> None:
    root = paths.KNOWLEDGE_ROOT
    assert probabilities_table().table
    routes = load_routes(root / "routes.toml")
    assert routes.underground_blocks
    structures = load_structure_maps(root / "structure_sets.toml")
    assert structures.set_for_table("minecraft:chests/village/village_temple") == "minecraft:villages"
    assert "minecraft:trial_chambers" in structures.underground_sets
