"""snapshot diff 計算 (Phase 3)."""

from __future__ import annotations

from ai_radar.crawler.benchmarks import BenchmarkEntry, BenchmarkSnapshot
from ai_radar.crawler.benchmarks.diff import compute_diff


def _snap(
    slug: str, entries: list[tuple[int, str, float | None]], at: int = 100
) -> BenchmarkSnapshot:
    return BenchmarkSnapshot(
        source_slug=slug,
        category="benchmark",
        captured_at=at,
        entries=tuple(
            BenchmarkEntry(rank=r, identifier=i, score=s, payload={}) for r, i, s in entries
        ),
        display_name=slug,
    )


def test_diff_first_snapshot_treats_all_as_new() -> None:
    """previous=None なら全 entry が new_entries に入る."""
    current = _snap("s", [(1, "A", 1.0), (2, "B", 0.9)])
    d = compute_diff(None, current)
    assert len(d.new_entries) == 2
    assert d.rank_up == ()
    assert d.rank_down == ()
    assert d.dropped == ()
    assert d.has_changes is True


def test_diff_no_change_has_no_changes() -> None:
    """全く同じ snapshot は has_changes=False."""
    prev = _snap("s", [(1, "A", 1.0), (2, "B", 0.9)], at=100)
    curr = _snap("s", [(1, "A", 1.0), (2, "B", 0.9)], at=200)
    d = compute_diff(prev, curr)
    assert d.has_changes is False


def test_diff_detects_new_entry() -> None:
    """前回に無い identifier は new_entries に入る."""
    prev = _snap("s", [(1, "A", 1.0)], at=100)
    curr = _snap("s", [(1, "A", 1.0), (2, "B", 0.5)], at=200)
    d = compute_diff(prev, curr)
    assert [e.identifier for e in d.new_entries] == ["B"]


def test_diff_detects_rank_up_with_min_delta() -> None:
    """min_rank_delta 以上の上昇のみ拾う (delta=2 デフォルト)."""
    prev = _snap("s", [(1, "A", 1.0), (2, "B", 0.9), (3, "C", 0.8)], at=100)
    # B が 2 → 1 (delta=1) → 拾わない. A が 1 → 3 (delta=-2) → rank_down
    curr = _snap("s", [(1, "B", 0.9), (2, "C", 0.8), (3, "A", 1.0)], at=200)
    d = compute_diff(prev, curr)
    assert [d.entry.identifier for d in d.rank_up] == []  # B の delta=1 は拾わない
    assert [d.entry.identifier for d in d.rank_down] == ["A"]


def test_diff_min_delta_one_picks_all_movements() -> None:
    """min_rank_delta=1 にすると 1 位の入れ替わりも拾う."""
    prev = _snap("s", [(1, "A", 1.0), (2, "B", 0.9)], at=100)
    curr = _snap("s", [(1, "B", 0.9), (2, "A", 1.0)], at=200)
    d = compute_diff(prev, curr, min_rank_delta=1)
    up_ids = sorted(d.entry.identifier for d in d.rank_up)
    down_ids = sorted(d.entry.identifier for d in d.rank_down)
    assert up_ids == ["B"]
    assert down_ids == ["A"]


def test_diff_detects_dropped_entries() -> None:
    """前回 ranked で今回圏外なら dropped."""
    prev = _snap("s", [(1, "A", 1.0), (2, "B", 0.9), (3, "C", 0.5)], at=100)
    curr = _snap("s", [(1, "A", 1.0), (2, "B", 0.9)], at=200)
    d = compute_diff(prev, curr)
    assert [d.entry.identifier for d in d.dropped] == ["C"]


def test_diff_has_changes_with_only_dropped() -> None:
    """dropped だけでも has_changes=True."""
    prev = _snap("s", [(1, "A", 1.0)], at=100)
    curr = _snap("s", [], at=200)
    d = compute_diff(prev, curr)
    assert d.has_changes is True
    assert len(d.dropped) == 1


def test_diff_records_previous_rank_for_movement() -> None:
    """rank_up / rank_down / dropped で previous_rank が保存される."""
    prev = _snap("s", [(1, "A", 1.0), (5, "B", 0.5)], at=100)
    curr = _snap("s", [(1, "B", 0.5)], at=200)  # B が 5→1, A が dropped
    d = compute_diff(prev, curr)
    assert d.rank_up[0].entry.identifier == "B"
    assert d.rank_up[0].previous_rank == 5
    assert d.dropped[0].entry.identifier == "A"
    assert d.dropped[0].previous_rank == 1
