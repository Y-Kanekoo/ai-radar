"""snapshot 差分計算 (Phase 3).

直前 snapshot と最新 snapshot を比較して 4 カテゴリに分類:

- ``new_entries``: 前回圏外 → 今回ランクイン
- ``rank_up``: 前回より順位上昇 (例: 7 → 3)
- ``rank_down``: 前回より順位下落 (例: 3 → 9)
- ``dropped``: 前回ランクイン → 今回圏外

差分のしきい値: rank_up / rank_down は ``min_delta=2`` 以上の変動のみ通知
(1 位だけの揺らぎは多すぎてノイズになる).
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_radar.crawler.benchmarks import BenchmarkEntry, BenchmarkSnapshot

DEFAULT_MIN_RANK_DELTA = 2


@dataclass(frozen=True)
class RankedDiff:
    """1 行の rank 変動. ``previous_rank`` は dropped でも前回の順位."""

    entry: BenchmarkEntry
    previous_rank: int


@dataclass(frozen=True)
class SnapshotDiff:
    """``compute_diff`` の戻り値."""

    new_entries: tuple[BenchmarkEntry, ...]
    rank_up: tuple[RankedDiff, ...]
    rank_down: tuple[RankedDiff, ...]
    dropped: tuple[RankedDiff, ...]

    @property
    def has_changes(self) -> bool:
        """通知に値する変化があるか."""
        return bool(self.new_entries or self.rank_up or self.rank_down or self.dropped)


def compute_diff(
    previous: BenchmarkSnapshot | None,
    current: BenchmarkSnapshot,
    *,
    min_rank_delta: int = DEFAULT_MIN_RANK_DELTA,
) -> SnapshotDiff:
    """直前 snapshot との差分を計算する.

    Args:
        previous: 直前 snapshot. None なら全 entry が ``new_entries`` に入る.
        current: 最新 snapshot.
        min_rank_delta: rank 変動の最小しきい値 (両端含む). 1 ならノイズが多い.

    Returns:
        SnapshotDiff. 通知対象が空なら全フィールド空タプル.
    """
    if previous is None:
        return SnapshotDiff(
            new_entries=tuple(current.entries),
            rank_up=(),
            rank_down=(),
            dropped=(),
        )

    prev_map = {e.identifier: e for e in previous.entries}
    curr_map = {e.identifier: e for e in current.entries}

    new_list: list[BenchmarkEntry] = []
    up_list: list[RankedDiff] = []
    down_list: list[RankedDiff] = []

    for entry in current.entries:
        prev = prev_map.get(entry.identifier)
        if prev is None:
            new_list.append(entry)
            continue
        delta = prev.rank - entry.rank  # 正なら上昇 (順位が下がった)
        if delta >= min_rank_delta:
            up_list.append(RankedDiff(entry=entry, previous_rank=prev.rank))
        elif -delta >= min_rank_delta:
            down_list.append(RankedDiff(entry=entry, previous_rank=prev.rank))

    dropped_list = [
        RankedDiff(entry=prev_map[ident], previous_rank=prev_map[ident].rank)
        for ident in prev_map
        if ident not in curr_map
    ]

    return SnapshotDiff(
        new_entries=tuple(new_list),
        rank_up=tuple(up_list),
        rank_down=tuple(down_list),
        dropped=tuple(dropped_list),
    )
