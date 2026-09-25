"""One-to-one detection ↔ track assignment at capture time (Hungarian + distance gate).

Greedy nearest-neighbour could assign two detections to one track; the 20 "trap" tracks that sit
7–26 m outside their frame make that a real risk at frame edges.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

_BIG = 1e9


@dataclass
class MatchPair:
    det_idx: int
    track_idx: int
    dist_m: float
    margin_m: float | None
    second_idx: int | None


@dataclass
class MatchResult:
    pairs: list[MatchPair] = field(default_factory=list)
    unmatched_dets: list[int] = field(default_factory=list)
    unmatched_tracks: list[int] = field(default_factory=list)


class TrackMatcher:
    def __init__(self, gate_m: float = 10.0):
        self.gate_m = gate_m

    def match(self, det_xy: np.ndarray, track_xy: np.ndarray, gates: np.ndarray | None = None) -> MatchResult:
        """det_xy [N, 2], track_xy [M, 2] in a shared metric frame; optional per-detection gate [N]."""
        n, m = len(det_xy), len(track_xy)
        if n == 0 or m == 0:
            return MatchResult(unmatched_dets=list(range(n)), unmatched_tracks=list(range(m)))
        dist = np.linalg.norm(det_xy[:, None, :] - track_xy[None, :, :], axis=2)
        gate = np.full(n, self.gate_m) if gates is None else np.maximum(np.asarray(gates, float), self.gate_m)
        cost = np.where(dist <= gate[:, None], dist, _BIG)
        rows, cols = linear_sum_assignment(cost)
        res = MatchResult()
        used_d, used_t = set(), set()
        for i, j in zip(rows, cols, strict=True):
            if cost[i, j] >= _BIG:
                continue
            order = np.argsort(dist[i])
            second = next((int(k) for k in order if k != j), None)
            margin = float(dist[i, second] - dist[i, j]) if second is not None else None
            res.pairs.append(MatchPair(int(i), int(j), float(dist[i, j]), margin, second))
            used_d.add(int(i))
            used_t.add(int(j))
        res.unmatched_dets = [i for i in range(n) if i not in used_d]
        res.unmatched_tracks = [j for j in range(m) if j not in used_t]
        return res
