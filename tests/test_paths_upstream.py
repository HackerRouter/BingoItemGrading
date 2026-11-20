"""`paths` 解析层与 `upstream` 同步/校验的行为锁定。

这些测试的目的不是覆盖率，而是把「依赖到底来自哪一层」变成可执行断言：
运行态只读 `data/`；`config.yml` 指向的上游只服务 `bg data sync` / `verify`。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bingo_grading import paths, upstream


@pytest.fixture()
def fake_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """造一个只有 data/ 与 ref/ 骨架的临时目录树，接管全部路径常量。"""
    data = tmp_path / "data"
    ref = tmp_path / "ref"
    monkeypatch.setattr(paths, "DATA_ROOT", data)
    monkeypatch.setattr(paths, "UPSTREAM_ROOT", data / "upstream")
    monkeypatch.setattr(paths, "REF_RECIPE_ANALYSIS", ref / "RecipeAnalysis")
    monkeypatch.setattr(paths, "REF_COLLECTOR", ref / "WorldGenStatsCollector")
    return tmp_path


def test_recipe_analysis_prefers_local(fake_layout: Path) -> None:
    local = paths.UPSTREAM_ROOT / "26.3" / "recipe-analysis"
    ref = paths.REF_RECIPE_ANALYSIS / "output" / "26.3"
    local.mkdir(parents=True)
    ref.mkdir(parents=True)

    resolved = paths.recipe_analysis("26.3")

    assert resolved.path == local
    assert resolved.layer == paths.LOCAL
    assert resolved.local


def test_recipe_analysis_ignores_ref(fake_layout: Path) -> None:
    """`ref/` 是 gitignore 目录、不可迁移，运行态不回退到它。"""
    ref = paths.REF_RECIPE_ANALYSIS / "output" / "26.3"
    ref.mkdir(parents=True)

    resolved = paths.recipe_analysis("26.3")

    assert resolved.path == paths.UPSTREAM_ROOT / "26.3" / "recipe-analysis"
    assert resolved.layer == paths.MISSING
    assert not resolved.local


def test_recipe_analysis_missing_when_neither_side_exists(fake_layout: Path) -> None:
    resolved = paths.recipe_analysis("26.3")

    assert resolved.layer == paths.MISSING
    assert not resolved.exists
    assert not resolved.local


def test_override_wins_and_counts_as_local(fake_layout: Path, tmp_path: Path) -> None:
    local = paths.UPSTREAM_ROOT / "26.3" / "recipe-analysis"
    local.mkdir(parents=True)

    resolved = paths.recipe_analysis("26.3", override=str(tmp_path / "elsewhere"))

    assert resolved.layer == paths.OVERRIDE
    assert resolved.local


def test_collector_run_picks_latest_local_run(fake_layout: Path) -> None:
    base = paths.UPSTREAM_ROOT / "26.3" / "worldgen-stats"
    for stamp in ("2026-01-01T00-00-00-000Z", "2026-02-02T00-00-00-000Z"):
        (base / stamp).mkdir(parents=True)

    resolved = paths.collector_run("26.3")

    assert resolved.path == base / "2026-02-02T00-00-00-000Z"
    assert resolved.layer == paths.LOCAL


def test_template_facts_follows_recipe_analysis_layer(fake_layout: Path) -> None:
    local = paths.UPSTREAM_ROOT / "26.3" / "recipe-analysis" / "facts"
    local.mkdir(parents=True)
    (local / "template.jsonl").write_text("{}\n", encoding="utf-8")

    resolved = paths.template_facts("26.3")

    assert resolved.layer == paths.LOCAL
    assert resolved.path.name == "template.jsonl"


def test_summary_reports_fully_local(fake_layout: Path) -> None:
    (paths.UPSTREAM_ROOT / "26.3" / "recipe-analysis").mkdir(parents=True)
    (paths.UPSTREAM_ROOT / "26.3" / "worldgen-stats" / "run").mkdir(parents=True)
    (paths.UPSTREAM_ROOT / "26.3" / "datapack" / "data" / "minecraft").mkdir(parents=True)

    summary = paths.summary("26.3")

    assert summary["fully_local"] is True
    assert set(summary["sources"]) == {"recipe_analysis", "collector_run", "datapack"}


def test_summary_reports_missing_without_local(fake_layout: Path) -> None:
    """上游目录存在也不算数：报告只看 `data/`。"""
    (paths.REF_RECIPE_ANALYSIS / "output" / "26.3").mkdir(parents=True)

    summary = paths.summary("26.3")

    assert summary["fully_local"] is False
    assert summary["sources"]["recipe_analysis"]["layer"] == paths.MISSING


# --------------------------------------------------------------- upstream


def test_tree_digest_is_order_and_mtime_independent(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    for root in (left, right):
        (root / "sub").mkdir(parents=True)
        (root / "a.txt").write_text("alpha", encoding="utf-8")
        (root / "sub" / "b.txt").write_text("beta", encoding="utf-8")

    first = upstream._tree_digest(left)
    second = upstream._tree_digest(right)
    assert first == second
    # 返回 (文件数, 字节数, 摘要)，摘要与遍历顺序无关。
    assert first[0] == 2
    assert first[2] == second[2]

    (right / "a.txt").write_text("alpha!", encoding="utf-8")
    assert upstream._tree_digest(right) != first


def test_tree_digest_ignores_empty_directories(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "a.txt").write_text("x", encoding="utf-8")
    baseline = upstream._tree_digest(root)

    (root / "empty").mkdir()
    assert upstream._tree_digest(root) == baseline


def test_copy_tree_mirrors_and_drops_stale_files(tmp_path: Path) -> None:
    """整包复制：源里有什么就复制什么，目标里多出来的会被清掉。"""
    source = tmp_path / "src"
    source.mkdir()
    (source / "keep.json").write_text("{}", encoding="utf-8")
    (source / "also.txt").write_text("x", encoding="utf-8")

    target = tmp_path / "dst"
    target.mkdir()
    (target / "stale.bin").write_bytes(b"\x00")

    files, total = upstream._copy_tree(source, target)

    assert files == 2
    assert total == 3
    assert (target / "keep.json").exists()
    assert (target / "also.txt").exists()
    assert not (target / "stale.bin").exists()


def test_verify_detects_tampering(fake_layout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    upstream_root = paths.UPSTREAM_ROOT / "26.3"
    source = fake_layout / "src" / "facts"
    source.mkdir(parents=True)
    (source / "recipe.jsonl").write_text('{"id": 1}\n', encoding="utf-8")

    target = upstream_root / "recipe-analysis"
    files, total = upstream._copy_tree(source, target)

    manifest = {
        "schema": upstream.MANIFEST_SCHEMA,
        "pack": "26.3",
        "entries": [
            {
                "kind": "recipe-analysis",
                "layer": paths.LOCAL,
                "source": str(source),
                "target": str(target),
                "files": files,
                "bytes": total,
                "digest": upstream._tree_digest(target)[2],
            }
        ],
    }
    (upstream_root / upstream.MANIFEST_NAME).write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    assert upstream.verify("26.3").ok

    (target / "recipe.jsonl").write_text('{"id": 2}\n', encoding="utf-8")

    result = upstream.verify("26.3")
    assert not result.ok
    assert any("digest" in problem or "摘要" in problem for problem in result.problems)


def test_verify_flags_missing_manifest(fake_layout: Path) -> None:
    (paths.UPSTREAM_ROOT / "26.3").mkdir(parents=True)

    result = upstream.verify("26.3")

    assert not result.ok


def test_verify_rejects_stale_manifest_schema(fake_layout: Path) -> None:
    """旧格式的 manifest 不能拿来逐条比对：kind 集合不同，结论会错。"""
    upstream_root = paths.UPSTREAM_ROOT / "26.3"
    upstream_root.mkdir(parents=True)
    (upstream_root / upstream.MANIFEST_NAME).write_text(
        json.dumps({"schema": upstream.MANIFEST_SCHEMA - 1, "pack": "26.3", "entries": []}),
        encoding="utf-8",
    )

    result = upstream.verify("26.3")

    assert not result.ok
    assert any("data sync" in problem for problem in result.problems)


def test_upstream_parsers_ignore_local_snapshot(fake_layout: Path) -> None:
    """同步取源只能看上上游，本地已有快照不能被当成源。"""
    local = paths.UPSTREAM_ROOT / "26.3" / "recipe-analysis"
    local.mkdir(parents=True)
    (local / "graph.json").write_text("{}", encoding="utf-8")

    # 解析要命中本地。
    assert paths.recipe_analysis("26.3").layer == paths.LOCAL
    # 取源不能。
    source = paths.upstream_recipe_analysis("26.3")
    assert source.layer == paths.MISSING
    assert source.path != local

    upstream_dir = paths.REF_RECIPE_ANALYSIS / "output" / "26.3"
    upstream_dir.mkdir(parents=True)
    assert paths.upstream_recipe_analysis("26.3").path == upstream_dir


def test_dry_run_matches_real_sync_counts(fake_layout: Path) -> None:
    """`--dry-run` 报的数字必须就是实跑会复制的东西，否则预览失去意义。"""
    run = fake_layout / "ref" / "WorldGenStatsCollector" / "stats" / "run-a"
    run.mkdir(parents=True)
    (run / "summary.json").write_text(
        json.dumps({"target": {"dataPacks": ["vanilla", "Pack_x"]}}), encoding="utf-8"
    )
    (run / "stats.json").write_text("{}", encoding="utf-8")
    (run / "note.txt").write_text("not json", encoding="utf-8")

    pack_src = fake_layout / "ref" / "WorldGenStatsCollector" / ".server" / "26.3"
    pack_src = pack_src / "world" / "datapacks" / "Pack_x"
    (pack_src / "data").mkdir(parents=True)
    (pack_src / "data" / "a.json").write_text("{}", encoding="utf-8")
    (pack_src / "README.md").write_text("x", encoding="utf-8")

    preview = upstream.sync("26.3", dry_run=True)
    assert not (paths.UPSTREAM_ROOT / "26.3" / "recipe-analysis").exists()
    assert preview.totals["files"] > 0

    actual = upstream.sync("26.3")
    assert actual.totals == preview.totals
    for entry in preview.entries:
        match = next(item for item in actual.entries if item.kind == entry.kind)
        assert (match.files, match.bytes) == (entry.files, entry.bytes)


def test_sync_source_layer_is_ref(fake_layout: Path) -> None:
    upstream_dir = paths.REF_RECIPE_ANALYSIS / "output" / "26.3"
    upstream_dir.mkdir(parents=True)
    (upstream_dir / "graph.json").write_text('{"rules": []}', encoding="utf-8")

    report = upstream.sync("26.3")

    entry = next(item for item in report.entries if item.kind == "recipe-analysis")
    assert entry.layer == paths.REF
    assert entry.source == str(upstream_dir)


def test_sync_prunes_older_runs(fake_layout: Path) -> None:
    """统计运行只留最新一次：旧 run 永远读不到，不该一直堆在 data/ 里。"""
    stats = fake_layout / "ref" / "WorldGenStatsCollector" / "stats"
    for name in ("2026-11-07T10-00-00-000Z", "2026-11-13T12-00-00-000Z"):
        run = stats / name
        run.mkdir(parents=True)
        (run / "summary.json").write_text(
            json.dumps({"target": {"dataPacks": ["vanilla"]}}), encoding="utf-8"
        )
        (run / "ore.json").write_text("{}", encoding="utf-8")

    stale = paths.UPSTREAM_ROOT / "26.3" / "worldgen-stats" / "2026-11-07T10-00-00-000Z"
    stale.mkdir(parents=True)
    (stale / "old.json").write_text("{}", encoding="utf-8")

    report = upstream.sync("26.3")

    assert report.removed == ["2026-11-07T10-00-00-000Z"]
    kept = paths.UPSTREAM_ROOT / "26.3" / "worldgen-stats"
    assert [p.name for p in kept.iterdir()] == ["2026-11-13T12-00-00-000Z"]


def test_dry_run_reports_pruned_runs_without_deleting(fake_layout: Path) -> None:
    stats = fake_layout / "ref" / "WorldGenStatsCollector" / "stats"
    run = stats / "2026-11-13T12-00-00-000Z"
    run.mkdir(parents=True)
    (run / "summary.json").write_text(
        json.dumps({"target": {"dataPacks": ["vanilla"]}}), encoding="utf-8"
    )
    (run / "ore.json").write_text("{}", encoding="utf-8")

    stale = paths.UPSTREAM_ROOT / "26.3" / "worldgen-stats" / "2026-11-07T10-00-00-000Z"
    stale.mkdir(parents=True)

    report = upstream.sync("26.3", dry_run=True)

    assert report.removed == ["2026-11-07T10-00-00-000Z"]
    assert stale.is_dir()


def test_preflight_reports_missing_inputs_with_the_upstream_command(
    fake_layout: Path,
) -> None:
    """解包产物不是上游仓库常驻的：缺了要说清「先跑哪条上游命令」。"""
    missing = upstream.missing_prerequisites("26.3")
    keys = {item.key for item in missing}
    assert {"ra_inputs", "ra_datapack_merged", "ra_output", "wgs_run"} <= keys

    ra_inputs = next(item for item in missing if item.key == "ra_inputs")
    assert "ra inputs init" in ra_inputs.action
    assert not ra_inputs.present


def test_preflight_is_quiet_once_the_upstream_has_been_built(fake_layout: Path) -> None:
    ra = paths.REF_RECIPE_ANALYSIS
    (ra / "inputs" / "26.3" / "data").mkdir(parents=True)
    (ra / "inputs" / "26.3" / "datapack-merged" / "data").mkdir(parents=True)
    (ra / "output" / "26.3").mkdir(parents=True)
    structure = ra / ".cache" / "server-abc" / "structures" / "data" / "minecraft" / "structure"
    structure.mkdir(parents=True)

    run = paths.REF_COLLECTOR / "stats" / "run-a"
    run.mkdir(parents=True)
    (run / "summary.json").write_text("{}", encoding="utf-8")

    assert upstream.missing_prerequisites("26.3") == []


