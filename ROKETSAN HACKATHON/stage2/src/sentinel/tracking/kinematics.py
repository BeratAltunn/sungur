"""Track kinematics relative to the base over the last `window_min` minutes."""

from __future__ import annotations

import numpy as np

from sentinel.config import TrackingCfg
from sentinel.domain.models import Kinematics, StopSegment, Track, hhmm
from sentinel.geo.geodesy import LocalFrame, bearing_deg, compass8
from sentinel.geo.zones import ZoneIndex


def compute_kinematics(
    track: Track,
    t_now: int,
    geo: LocalFrame,
    zones: ZoneIndex,
    cfg: TrackingCfg,
) -> Kinematics:
    pts = [p for p in track.points if t_now - cfg.window_min <= p.t_min <= t_now]
    if not pts:
        raise ValueError(f"{track.track_id}: {hhmm(t_now)} penceresinde nokta yok")
    t = np.array([p.t_min for p in pts], dtype=float)
    x, y = geo.to_local([p.lat for p in pts], [p.lon for p in pts])
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    d = np.hypot(x, y)

    seg_len = np.hypot(np.diff(x), np.diff(y))
    seg_dt = np.diff(t) * 60.0
    seg_v = np.divide(seg_len, seg_dt, out=np.zeros_like(seg_len), where=seg_dt > 0)
    path = float(seg_len.sum())
    duration_s = float((t[-1] - t[0]) * 60.0)

    # closing speed and heading over the last N minutes
    k = int(np.searchsorted(t, t[-1] - cfg.closing_window_min, side="left"))
    k = min(k, len(t) - 1)
    dt_c = (t[-1] - t[k]) * 60.0
    closing = float((d[k] - d[-1]) / dt_c) if dt_c > 0 else 0.0
    vx, vy = x[-1] - x[k], y[-1] - y[k]
    v_norm = float(np.hypot(vx, vy))
    heading = bearing_deg(vx, vy) if v_norm > 1.0 else None
    if v_norm > 1.0 and d[-1] > 1.0:
        align = float((vx * -x[-1] + vy * -y[-1]) / (v_norm * d[-1]))
    else:
        align = 0.0

    stops = _stop_segments(t, seg_v, cfg)
    approaching = closing > cfg.approach_closing_mps and align > cfg.approach_align
    eta = float(d[-1] / closing / 60.0) if approaching and closing > 0 else None

    zones_passed: list[str] = []
    for p in pts:
        z = zones.zone_of(p.lat, p.lon)
        if not zones_passed or zones_passed[-1] != z:
            zones_passed.append(z)

    return Kinematics(
        track_id=track.track_id,
        t_now=hhmm(t[-1]),
        d_now_m=float(d[-1]),
        d_start_m=float(d[0]),
        d_change_m=float(d[0] - d[-1]),
        closing_mps=closing,
        align_cos=align,
        speed_now_mps=float(seg_v[-1]) if len(seg_v) else 0.0,
        speed_mean_mps=path / duration_s if duration_s > 0 else 0.0,
        speed_max_mps=float(seg_v.max()) if len(seg_v) else 0.0,
        path_m=path,
        heading_deg=heading,
        heading_dir=compass8(heading) if heading is not None else None,
        stops=stops,
        stop_total_min=sum(s.minutes for s in stops),
        stop_and_go=bool(stops) and approaching,
        approaching=approaching,
        leaving=closing < cfg.leaving_closing_mps,
        eta_min=eta,
        zones_passed=zones_passed,
        window=(hhmm(t[0]), hhmm(t[-1])),
        d_series=[(hhmm(tt), float(dd)) for tt, dd in zip(t, d, strict=True)],
    )


def _stop_segments(t: np.ndarray, seg_v: np.ndarray, cfg: TrackingCfg) -> list[StopSegment]:
    """Runs of ≥ stop_min_steps consecutive segments slower than stop_speed_mps."""
    out: list[StopSegment] = []
    i = 0
    while i < len(seg_v):
        if seg_v[i] >= cfg.stop_speed_mps:
            i += 1
            continue
        j = i
        while j < len(seg_v) and seg_v[j] < cfg.stop_speed_mps:
            j += 1
        if j - i >= cfg.stop_min_steps:
            out.append(StopSegment(start=hhmm(t[i]), end=hhmm(t[j]), minutes=int(t[j] - t[i])))
        i = j
    return out


def is_stationary(
    track: Track, t_from: float, t_to: float, geo: LocalFrame, max_disp_m: float
) -> tuple[bool, float, float]:
    """(stationary?, max displacement from first point in m, covered minutes) within [t_from, t_to]."""
    pts = [p for p in track.points if t_from <= p.t_min <= t_to]
    if len(pts) < 2:
        return False, 0.0, 0.0
    x, y = geo.to_local([p.lat for p in pts], [p.lon for p in pts])
    disp = float(np.max(np.hypot(np.asarray(x) - x[0], np.asarray(y) - y[0])))
    return disp <= max_disp_m, disp, float(pts[-1].t_min - pts[0].t_min)


def closing_at(track: Track, t_at: float, geo: LocalFrame, window_min: float) -> tuple[float, float] | None:
    """(closing m/s, speed m/s) over [t_at − window, t_at] from grid points; None if not covered."""
    pts = [p for p in track.points if t_at - window_min <= p.t_min <= t_at]
    if len(pts) < 2:
        return None
    a, b = pts[0], pts[-1]
    dt = (b.t_min - a.t_min) * 60.0
    da = float(geo.dist_to_origin_m(a.lat, a.lon))
    db = float(geo.dist_to_origin_m(b.lat, b.lon))
    moved = float(geo.distance_m(a.lat, a.lon, b.lat, b.lon))
    return (da - db) / dt, moved / dt
