"""Calibration report: system levels vs. the blind gold set + weight sensitivity.

    python scripts/calibrate.py                 # report → runs/calibration.md (and printed)
    python scripts/calibrate.py --delta 0.2     # sensitivity step (±20 %)

Works without labels too: then it shows the level distribution and the sensitivity table only.
Targets (PROJECT_DESIGN §1.7): KRİTİK/YÜKSEK recall 100 %, false alarm ≤ 20 %.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sentinel.risk.calibration import (  # noqa: E402
    LEVELS,
    LabelStore,
    cohen_kappa,
    compare,
    consensus,
    levels_for,
    sensitivity,
)
from sentinel.service import SentinelService  # noqa: E402


def pct(x: float | None) -> str:
    return "—" if x is None else f"%{x * 100:.0f}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--delta", type=float, default=0.2)
    a = ap.parse_args()

    svc = SentinelService(use_llm=False)
    packets = [svc.packet(m.image_id) for m in svc.repo.frames()]
    system = levels_for(packets, svc.s.risk)
    labels = LabelStore(svc.s.path(svc.s.observability.labels_dir)).latest()
    out: list[str] = ["# Kalibrasyon raporu", ""]

    dist = Counter(lv.value for lv in system.values())
    out.append(f"Detektör: `{svc.detector.name}` · {len(system)} kare")
    out.append("")
    out.append(
        "Sistem seviye dağılımı: "
        + " · ".join(f"{lv.value} {dist.get(lv.value, 0)}" for lv in reversed(LEVELS))
    )
    out.append("")

    # ---- labelers and agreement
    out.append("## Altın set")
    if not labels:
        out.append("")
        out.append("Henüz etiket yok. Arayüzde kör etiketleme modunu açın (`#/label`).")
    else:
        for name, per in labels.items():
            out.append(f"- `{name}`: {len(per)}/{len(system)} kare")
        names = list(labels)
        if len(names) >= 2:
            a1, a2 = labels[names[0]], labels[names[1]]
            common = sorted(set(a1) & set(a2))
            k = cohen_kappa([a1[i].level for i in common], [a2[i].level for i in common])
            agree = sum(a1[i].level == a2[i].level for i in common)
            out.append("")
            out.append(
                f"Etiketleyici uyumu ({names[0]} ↔ {names[1]}, {len(common)} ortak kare): "
                f"birebir {agree}/{len(common)}, ağırlıklı Cohen's κ = {k:.2f}"
                if k is not None
                else "κ hesaplanamadı"
            )
            dis = [i for i in common if a1[i].level != a2[i].level]
            if dis:
                out.append("")
                out.append("Uyuşmayan kareler (konsensüs: yüksek olan seviye, önce recall):")
                for i in dis:
                    out.append(f"- {i}: {names[0]} {a1[i].level.value} · {names[1]} {a2[i].level.value}")

        gold = consensus(labels)
        m = compare(system, gold)
        out += ["", "## Sistem ↔ altın set", ""]
        out.append(
            f"{m.n} kare karşılaştırıldı · birebir {m.exact}/{m.n} · ±1 kademe içinde {m.within_one}/{m.n}"
        )
        out.append("")
        out.append(f"- **YÜKSEK/KRİTİK recall:** {pct(m.high_recall)} (hedef %100)")
        out.append(
            f"- **Kaçırılan tehdit** (altın ≥ YÜKSEK, sistem < ORTA): {len(m.missed_threats)} {m.missed_threats or ''}"
        )
        out.append(
            f"- Düşük verilen (altın ≥ YÜKSEK, sistem < YÜKSEK): {len(m.under_called)} {m.under_called or ''}"
        )
        out.append(
            f"- **Yanlış alarm oranı** (sistem ≥ YÜKSEK ama altın daha düşük): {pct(m.false_alarm_rate)} (hedef ≤ %20) {m.false_alarms or ''}"
        )
        out += ["", "Karışıklık matrisi (satır = altın, sütun = sistem):", ""]
        out.append("| altın \\ sistem | " + " | ".join(lv.value for lv in LEVELS) + " |")
        out.append("|---|" + "---|" * len(LEVELS))
        for lv, row in zip(LEVELS, m.confusion, strict=True):
            out.append(f"| {lv.value} | " + " | ".join(str(x) for x in row) + " |")

    # ---- sensitivity
    out += ["", f"## Duyarlılık (her ağırlık ±%{a.delta * 100:.0f})", ""]
    d = round(a.delta * 100)
    out.append(f"| ağırlık | değer | −%{d} → değişen kare | +%{d} → değişen kare |")
    out.append("|---|---|---|---|")
    for r in sensitivity(packets, svc.s.risk, a.delta):
        out.append(f"| {r['weight']} | {r['value']} | {r['down']} | {r['up']} |")
    out.append("")
    out.append(
        "Taban kuralları (KRİTİK/YÜKSEK tabanı) ağırlıklardan bağımsızdır; bu tablo yalnızca skor kısmını ölçer."
    )

    report = "\n".join(out) + "\n"
    dest = svc.s.path(svc.s.observability.runs_dir) / "calibration.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(report, encoding="utf-8")
    print(report)
    print(f"rapor: {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
