"""Stopwatch test (PROJECT_DESIGN §5.2): how long does one frame take by hand vs. with the system?

    python scripts/stopwatch.py manual img_005672 --who ayse     # raw files only, no system
    python scripts/stopwatch.py system img_001230 --who ayse     # with the web UI
    python scripts/stopwatch.py summary                          # averages → numbers for the pitch

Use DIFFERENT frames for the two modes (otherwise the second run benefits from memory).
Results are appended to calibration/stopwatch.csv (committed, so the team shares them).
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "calibration" / "stopwatch.csv"
FIELDS = [
    "at",
    "who",
    "mode",
    "image_id",
    "seconds",
    "level",
    "vehicles",
    "nearest_km",
    "approaching",
    "contradicted_reports",
    "note",
]

QUESTIONS = """Kare için şu 5 soruyu cevaplayın (cevapları aşağıda kaydedeceğiz):
  1. Karede kaç araç var?
  2. Üsse en yakın araç kaç km uzakta ve üsse yaklaşıyor mu? (son 10 dk)
  3. Hangi araçlar yaklaşıyor? (sayı)
  4. Son 2 saatteki ilgili raporlardan hangileri kanıtla çelişiyor? (sayı)
  5. Bu kare için risk seviyesi: DÜŞÜK / ORTA / YÜKSEK / KRİTİK"""

MANUAL_KIT = """ELLE ANALİZ: sistemi (arayüz, CLI, sohbet) ve yapay zekâ araçlarını KULLANMAYIN. Yalnızca ham dosyalar
({data}):
  - görüntü:  images/{img}.jpg
  - köşe koordinatları ve çekim saati: image_meta.json  → "{img}"
  - hareket kayıtları: tracks.csv  (track_id,time,lat,lon; 5 dk aralıklı)
  - saha raporları: field_reports.json
  - üs ve bölgeler: zones.json
  Hesap makinesi, tablo programı ve harita (ör. Google Maps'te koordinat arama) serbest."""

SYSTEM_KIT = (
    """SİSTEMLE ANALİZ: http://127.0.0.1:8000/#/frame/{img} adresini açın ve cevapları ekrandan okuyun."""
)


def _data_dir() -> Path:
    """The package the system runs on (config.yaml → data_dir / SENTINEL_DATA_DIR), so both modes see the same data."""
    sys.path.insert(0, str(ROOT / "src"))
    from sentinel.config import load_settings

    return load_settings().data_path.resolve()


_LEVELS = {"dusuk": "DÜŞÜK", "orta": "ORTA", "yuksek": "YÜKSEK", "kritik": "KRİTİK"}
_TR = str.maketrans("çğıöşüÇĞİIÖŞÜ", "cgiosucgiiosu")


def _level(text: str) -> str:
    """'kritik', 'KRİTİK', 'Yüksek' … → canonical level (Python's upper() would turn i into I, not İ)."""
    return _LEVELS.get(text.strip().translate(_TR).lower(), text.strip())


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def run(mode: str, img: str, who: str) -> None:
    print("\n" + (MANUAL_KIT if mode == "manual" else SYSTEM_KIT).format(img=img, data=_data_dir()))
    print("\n" + QUESTIONS)
    ask("\nHazır olunca Enter'a basın; süre başlar… ")
    t0 = time.monotonic()
    ask("Beş sorunun cevabı hazır olunca Enter'a basın… ")
    sec = round(time.monotonic() - t0, 1)
    print(f"\nSüre: {sec / 60:.1f} dk ({sec:.0f} sn). Cevapları girin (boş geçilebilir):")
    row = {
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "who": who,
        "mode": mode,
        "image_id": img,
        "seconds": sec,
        "vehicles": ask("  1. araç sayısı: "),
        "nearest_km": ask("  2. en yakın aracın üsse mesafesi (km): "),
        "approaching": ask("  3. yaklaşan araç sayısı: "),
        "contradicted_reports": ask("  4. çelişen rapor sayısı: "),
        "level": _level(ask("  5. seviye: ")),
        "note": ask("  not: "),
    }
    new = not OUT.exists()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
    print(f"Kaydedildi → {OUT}")


def summary() -> None:
    if not OUT.exists():
        print("Henüz ölçüm yok.")
        return
    rows = list(csv.DictReader(OUT.open(encoding="utf-8")))
    by: dict[str, list[float]] = {}
    for r in rows:
        by.setdefault(r["mode"], []).append(float(r["seconds"]))
    for mode, xs in by.items():
        name = "Elle" if mode == "manual" else "Sistemle"
        print(
            f"{name:9} n={len(xs)}  ortalama {statistics.mean(xs) / 60:.1f} dk  medyan {statistics.median(xs) / 60:.1f} dk"
        )
    if "manual" in by and "system" in by:
        m, s = statistics.mean(by["manual"]), statistics.mean(by["system"])
        print(f"\nKare başına kazanç: {m / 60:.1f} dk → {s / 60:.1f} dk (%{(1 - s / m) * 100:.0f} azalma)")
        print(f"Günde 40 kare: {40 * m / 3600:.1f} saat → {40 * s / 3600:.1f} saat")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["manual", "system", "summary"])
    ap.add_argument("image_id", nargs="?")
    ap.add_argument("--who", default="")
    a = ap.parse_args()
    if a.mode == "summary":
        summary()
        return 0
    if not a.image_id or not a.who:
        ap.error("manual/system için image_id ve --who gerekli")
    run(a.mode, a.image_id, a.who)
    return 0


if __name__ == "__main__":
    sys.exit(main())
