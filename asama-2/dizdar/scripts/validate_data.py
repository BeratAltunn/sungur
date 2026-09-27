"""Validate a data package (dev or official) against the facts the pipeline relies on.

    python scripts/validate_data.py [data_dir]

Run this first when the official Stage 2 package arrives (PROJECT_DESIGN §4.4 risk 5).
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sentinel.config import load_settings  # noqa: E402
from sentinel.data.adapters import DataError  # noqa: E402
from sentinel.data.repository import Repository  # noqa: E402
from sentinel.geo.georef import GeoReferencer  # noqa: E402
from sentinel.reports.parser import ReportParser  # noqa: E402


def main() -> int:
    s = load_settings()
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else s.data_path
    print(f"Veri: {data_dir}")
    try:
        repo = Repository(data_dir, s.images_subdir)
    except DataError as e:
        print(f"✗ şema hatası: {e}")
        return 1
    problems: list[str] = []

    sizes = Counter((m.width_px, m.height_px) for m in repo.meta.values())
    print(f"✓ {len(repo.meta)} kare, boyutlar {dict(sizes)}")
    missing = [i for i in repo.meta if not repo.image_path(i).exists()]
    if missing:
        problems.append(f"{len(missing)} görüntü dosyası yok: {missing[:5]}")
    skew = [
        i
        for i, m in repo.meta.items()
        if m.corner_coordinates.top_left[0] != m.corner_coordinates.top_right[0]
        or m.corner_coordinates.top_left[1] != m.corner_coordinates.bottom_left[1]
    ]
    print(
        f"{'✓' if not skew else '!'} eksene hizalı olmayan kare: {len(skew)} (bilineer georef bunu karşılar)"
    )

    lens = Counter(len(t.points) for t in repo.tracks.values())
    print(f"✓ {len(repo.tracks)} track, nokta sayıları {dict(lens)}")
    captures = {m.capture_min for m in repo.meta.values()}
    off = [t.track_id for t in repo.tracks.values() if t.t_end not in captures]
    if off:
        problems.append(f"{len(off)} track'in son noktası bir çekim saatine denk gelmiyor")
    outside = 0
    for t in repo.tracks.values():
        last = t.points[-1]
        frames = [GeoReferencer(m) for m in repo.meta.values() if m.capture_min == last.t_min]
        if frames and not any(g.contains(last.lat, last.lon) for g in frames):
            outside += 1
    print(f"✓ çekim anında karenin dışında kalan track (tuzak): {outside}")

    claims = ReportParser(repo.zone_index.names()).parse_all(repo.reports)
    types = Counter("+".join(c.types) for c in claims.values())
    unknown = [rid for rid, c in claims.items() if "UNKNOWN" in c.types]
    print(
        f"✓ {len(repo.reports)} rapor, koordinatlı {sum(c.has_point for c in claims.values())}, iddia tipleri {dict(types)}"
    )
    if unknown:
        problems.append(f"{len(unknown)} rapor ayrıştırılamadı (LLM toplu ayrıştırma adayı): {unknown[:8]}")

    for p in problems:
        print(f"✗ {p}")
    print("SONUÇ: " + ("temiz" if not problems else f"{len(problems)} sorun"))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
