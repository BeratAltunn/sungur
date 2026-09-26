"""Detector acceptance report: run a candidate detector on every frame and compare it with a baseline.

    python scripts/compare_detectors.py --kind ultralytics --weights models/yolov8n.pt
    python scripts/compare_detectors.py --kind dfine --weights models/dfine_m_kaggle.pth
    python scripts/compare_detectors.py --kind callable --target kaggle_infer:predict --tau 0.3

The 40 Stage 2 frames have no box labels, so the tracks are used as a proxy ground truth:
  recall≈   = tracks inside the frame that got a matched detection / tracks inside the frame
  eşleşme%  = confident detections confirmed by a track / confident detections
Unmatched detections are either false positives or genuinely unregistered vehicles; those closer
than floor_high_untracked_km raise the frame to YÜKSEK, so they are listed explicitly.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sentinel.config import load_settings  # noqa: E402
from sentinel.data.repository import Repository  # noqa: E402
from sentinel.geo.georef import GeoReferencer  # noqa: E402
from sentinel.perception.factory import build_detector  # noqa: E402
from sentinel.perception.oracle import OracleDetector  # noqa: E402
from sentinel.pipeline import Pipeline  # noqa: E402


def _nearest_track_m(repo: Repository, lat: float, lon: float, t: int) -> float | None:
    ids, pos = repo.tracks_at(t)
    if not ids:
        return None
    return float(np.min(repo.geo.distance_m(lat, lon, pos[:, 0], pos[:, 1])))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="ultralytics", choices=["ultralytics", "dfine", "callable"])
    ap.add_argument("--weights", default=None)
    ap.add_argument("--target", default=None, help="callable: modul:predict")
    ap.add_argument("--tau", type=float, default=None, help="τ_op (varsayılan config)")
    ap.add_argument("--gate", type=float, default=None, help="eşleme kapısı m (varsayılan config)")
    ap.add_argument("--device", default=None)
    ap.add_argument("--images", default=None, help="virgülle ayrılmış kare listesi (varsayılan: hepsi)")
    ap.add_argument("--refresh", action="store_true", help="tespit önbelleğini yok say")
    a = ap.parse_args()

    s = load_settings()
    s.detector.kind = a.kind
    if a.weights:
        s.detector.ultralytics.weights = s.detector.dfine.weights = a.weights
    if a.target:
        s.detector.callable.target = a.target
    if a.tau is not None:
        s.detector.tau_op = a.tau
    if a.gate is not None:
        s.tracking.gate_m = a.gate
    if a.device:
        s.detector.ultralytics.device = s.detector.dfine.device = a.device

    repo = Repository(s.data_path, s.images_subdir)
    cand = Pipeline(s, repo, build_detector(s, repo))
    base = Pipeline(s, repo, OracleDetector(repo))
    images = a.images.split(",") if a.images else [m.image_id for m in repo.frames()]
    name = cand.detector.name
    print(f"aday={name}  τ_op={s.detector.tau_op}  kapı={s.tracking.gate_m} m  kare={len(images)}\n")

    rows, match_d, unmatched_near, labels = [], [], [], Counter()
    t0 = time.perf_counter()
    for img in images:
        meta = repo.meta[img]
        pb = base.evaluate(img)
        pc = cand.evaluate(img, refresh_detections=a.refresh)
        g = GeoReferencer(meta)
        ids, pos = repo.tracks_at(meta.capture_min)
        in_frame = {tid for tid, (la, lo) in zip(ids, pos, strict=True) if g.contains(float(la), float(lo))}
        matched = {v.track_id for v in pc.vehicles if v.track_id}
        untracked = [v for v in pc.vehicles if not v.track_id]
        labels.update(v.label for v in pc.vehicles)
        match_d += [v.match_m for v in pc.vehicles if v.match_m is not None]
        for v in untracked:
            unmatched_near.append(_nearest_track_m(repo, v.lat, v.lon, meta.capture_min))
        rows.append(
            {
                "image_id": img,
                "tespit": len(pc.vehicles),
                "düşük_güven": len(pc.low_conf),
                "trackler": len(in_frame),
                "eşleşen": len(matched & in_frame),
                "track'siz": len(untracked),
                "track'siz_<2km": sum(
                    v.d_base_m < s.risk.floor_high_untracked_km * 1000
                    and v.conf >= s.risk.floor_high_untracked_min_conf
                    for v in untracked
                ),
                "seviye_oracle": pb.risk.level.value,
                "seviye_aday": pc.risk.level.value,
                "skor_oracle": pb.risk.score,
                "skor_aday": pc.risk.score,
            }
        )
    dt = time.perf_counter() - t0

    print(f"{'kare':<11} {'tesp':>4} {'düş':>4} {'trk':>4} {'eşl':>4} {'tsız':>4}  seviye (oracle → aday)")
    for r in rows:
        ch = "" if r["seviye_oracle"] == r["seviye_aday"] else "  ←"
        print(
            f"{r['image_id']:<11} {r['tespit']:>4} {r['düşük_güven']:>4} {r['trackler']:>4} {r['eşleşen']:>4} "
            f"{r["track'siz"]:>4}  {r['seviye_oracle']:<7} → {r['seviye_aday']}{ch}"
        )

    tot = {
        k: sum(r[k] for r in rows) for k in ("tespit", "trackler", "eşleşen", "track'siz", "track'siz_<2km")
    }
    recall = tot["eşleşen"] / tot["trackler"] if tot["trackler"] else 0
    precision = (tot["tespit"] - tot["track'siz"]) / tot["tespit"] if tot["tespit"] else 0
    changed = [r for r in rows if r["seviye_oracle"] != r["seviye_aday"]]
    near_gate = [
        d for d in unmatched_near if d is not None and s.tracking.gate_m < d <= 3 * s.tracking.gate_m
    ]

    summary = {
        "detector": name,
        "tau_op": s.detector.tau_op,
        "gate_m": s.tracking.gate_m,
        "frames": len(rows),
        "sec_total": round(dt, 1),
        "recall_proxy": round(recall, 3),
        "track_confirmed_ratio": round(precision, 3),
        "labels": dict(labels),
        "match_m_median": round(statistics.median(match_d), 2) if match_d else None,
        "match_m_p90": round(float(np.percentile(match_d, 90)), 2) if match_d else None,
        "untracked": tot["track'siz"],
        "untracked_lt_2km": tot["track'siz_<2km"],
        "untracked_within_1to3x_gate": len(near_gate),
        "level_changes": len(changed),
        "levels_oracle": dict(Counter(r["seviye_oracle"] for r in rows)),
        "levels_candidate": dict(Counter(r["seviye_aday"] for r in rows)),
    }
    print("\nÖZET")
    print(f"  recall≈ {recall:.0%}  (karedeki {tot['trackler']} track'in {tot['eşleşen']}'i bulundu)")
    print(
        f"  track ile doğrulanan tespit oranı {precision:.0%}  ({tot['tespit']} tespit, {tot["track'siz"]} track'siz)"
    )
    print(f"  sınıflar {dict(labels)}")
    print(
        f"  eşleme mesafesi medyan {summary['match_m_median']} m, p90 {summary['match_m_p90']} m (kapı {s.tracking.gate_m} m)"
    )
    if near_gate:
        print(
            f"  ! {len(near_gate)} track'siz tespitin en yakın track'i kapının 1–3 katı mesafede → kapıyı gevşetmeyi değerlendirin"
        )
    print(f"  üsse < 2 km track'siz tespit (YÜKSEK tabanı tetikler): {tot["track'siz_<2km"]}")
    print(
        f"  seviye dağılımı oracle {summary['levels_oracle']} → aday {summary['levels_candidate']}  ({len(changed)} kare değişti)"
    )
    print(f"  süre {dt:.1f} sn ({dt / max(1, len(rows)):.2f} sn/kare)")

    out = s.path(s.observability.runs_dir) / f"compare_{name.replace(':', '_').replace('/', '_')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"summary": summary, "frames": rows}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"\nrapor: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
