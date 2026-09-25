"""CLI: backup demo path and test harness.

sentinel evaluate img_000860 [--json] [--no-llm] [--live]
sentinel batch [--json] [--no-llm]
sentinel reports [--zone Dogu\\ Yolu]
sentinel demo-check
"""

from __future__ import annotations

import argparse
import json
import sys

from sentinel.domain.models import LABEL_TR, EvaluationResult, Verdict
from sentinel.fmt import dec, km
from sentinel.geo.zones import zone_display
from sentinel.service import SentinelService

# Expected levels for the demo frames (make demo-check). Update after calibration.
DEMO_EXPECT = {"img_000860": "KRİTİK"}


def _print_eval(res: EvaluationResult) -> None:
    p, b = res.packet, res.brief
    f = p.frame
    print(f"\n{'═' * 96}")
    print(
        f" {p.image_id} · {zone_display(f.zone)} · {f.capture_time} · üsten {km(f.d_base_m)} {f.direction}"
        f"   │  {b.risk_level.icon} {b.risk_level.value}  (skor {p.risk.score})"
    )
    print(f"{'═' * 96}")
    print(f" BRIEF  {b.headline}")
    for kf in b.key_findings:
        print(f"   • {kf.statement}")
    print(f" Önerilen eylem: {b.recommended_action}")
    g = res.grounding
    badge = (
        f"✓ {g.checked}/{g.checked} sayı kanıtla doğrulandı"
        if g.passed
        else f"✗ grounding: {g.failed + g.unknown_refs}"
    )
    src = {"llm": "LLM", "llm_cache": "LLM (önbellek)", "template": "kural tabanlı şablon"}[res.brief_source]
    print(f" Güven: {b.confidence}   {badge}   Kaynak: {src}")
    if res.llm_note:
        print(f" Not: {res.llm_note}")
    if b.uncertainties:
        print(" Belirsizlik: " + " · ".join(b.uncertainties))

    print(f"\n── Neden? (faktör katkıları) {'─' * 66}")
    if p.risk.floor_level:
        print(f"   TABAN KURALI → {p.risk.floor_level.value}: " + "; ".join(p.risk.floor_reasons[:2]))
    for v in sorted(p.vehicles, key=lambda v: -v.score):
        print(
            f"   {v.ref} [{v.track_id or 'track yok'}] skor {v.score}: "
            + ", ".join(f"{x.label} {x.points:+d}" for x in v.factors)
        )
    for x in p.risk.factors:
        print(f"   Kare: {x.label} {x.points:+d}")

    print(f"\n── Araçlar ve kinematik {'─' * 71}")
    for v in p.vehicles:
        k = v.kinematics
        head = f"   {v.ref} {LABEL_TR[v.label]:<9} conf {dec(v.conf, 2)}  {v.track_id or '—':<6}"
        if v.track_id:
            head += f" eşleme {dec(v.match_m, 1)} m (marj {dec(v.margin_m or 0, 0)} m)"
        print(head)
        if k:
            eta = f" ETA ~{dec(k.eta_min)} dk" if k.eta_min is not None else ""
            stops = ", ".join(f"{s.start}–{s.end}" for s in k.stops) or "yok"
            print(
                f"        üsse {km(k.d_now_m)} (2 saat önce {km(k.d_start_m)}), yaklaşma {dec(k.closing_mps)} m/s, "
                f"hiza {dec(k.align_cos, 2)}{eta}; yol {km(k.path_m)}; duraklamalar: {stops}"
            )
    if p.undetected_tracks:
        print(f"   Karede olup tespit edilmeyen track: {', '.join(p.undetected_tracks)}")

    counts = {vd: sum(r.verdict == vd for r in p.reports) for vd in Verdict}
    print(
        f"\n── Raporlar  ✓{counts[Verdict.DOGRULANDI]} ✗{counts[Verdict.CELISIYOR]} "
        f"?{counts[Verdict.DOGRULANAMAZ]} İlgisiz {counts[Verdict.ILGISIZ]} {'─' * 52}"
    )
    for r in p.reports:
        if r.verdict == Verdict.ILGISIZ:
            continue
        print(f"   {r.verdict.icon} {r.report_id} {r.time} {r.source:<11} {r.text}")
        print(f"        → {r.reason}  [{r.relevance}]")
    print(
        f"\n run_id={res.run_id}  süre: çekirdek {res.timings_ms['core']:.0f} ms, brief {res.timings_ms['brief']:.0f} ms\n"
    )


def cmd_evaluate(svc: SentinelService, a: argparse.Namespace) -> int:
    res = svc.evaluate(a.image_id, live=a.live, use_llm=not a.no_llm)
    if a.json:
        print(res.model_dump_json(indent=1))
    else:
        _print_eval(res)
    return 0


def cmd_batch(svc: SentinelService, a: argparse.Namespace) -> int:
    results = [svc.evaluate(m.image_id, use_llm=not a.no_llm) for m in svc.repo.frames()]
    rows = svc.triage()
    if a.json:
        print(json.dumps([r.model_dump(mode="json") for r in rows], ensure_ascii=False, indent=1))
        return 0
    summ = svc.shift_summary()
    print(
        f"\nNÖBET DEVRİ  {summ.frames} kare · {summ.reports} rapor işlendi   "
        + "  ".join(f"{k} {v}" for k, v in summ.by_level.items())
    )
    print(f"{'─' * 110}")
    for r in rows:
        print(
            f"{r.level.icon:<2} {r.level.value:<7} {r.score:>3}  {r.image_id}  {zone_display(r.zone):<24} {r.capture_time}  "
            f"{km(r.d_base_m):>7}  ✗{r.reports_contradicted} ✓{r.reports_confirmed}  {r.headline[:60]}"
        )
    failed = [r for r in results if not r.grounding.passed]
    print(
        f"\n{len(results)} kare · grounding başarısız: {len(failed)} · brief kaynağı: "
        + ", ".join(
            f"{s}={sum(r.brief_source == s for r in results)}" for s in ("llm", "llm_cache", "template")
        )
    )
    return 0


def cmd_reports(svc: SentinelService, a: argparse.Namespace) -> int:
    reps = svc.find_reports(zone=a.zone)
    for r in reps:
        print(f"{r.verdict.icon} {r.report_id} {r.time} {r.source:<11} {r.text}\n      → {r.reason}")
    counts = {vd.value: sum(r.verdict == vd for r in reps) for vd in Verdict}
    print(f"\n{len(reps)} rapor: {counts}")
    return 0


def cmd_demo_check(svc: SentinelService, a: argparse.Namespace) -> int:
    ok = True
    for img, expect in DEMO_EXPECT.items():
        res = svc.evaluate(img, use_llm=not a.no_llm)
        good = res.brief.risk_level.value == expect and res.grounding.passed
        ok &= good
        print(
            f"{'✓' if good else '✗'} {img}: seviye {res.brief.risk_level.value} (beklenen {expect}), grounding {res.grounding.passed}"
        )
    print("demo-check " + ("YEŞİL" if ok else "KIRMIZI"))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sentinel", description="NÖBETÇİ: saha raporu destekli üs risk ajanı")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("evaluate", help="tek kareyi değerlendir")
    e.add_argument("image_id")
    e.add_argument("--json", action="store_true")
    e.add_argument("--no-llm", action="store_true", help="LLM'siz, kural tabanlı brief")
    e.add_argument("--live", action="store_true", help="tespit önbelleğini atla")
    b = sub.add_parser("batch", help="tüm kareler + triage sırası")
    b.add_argument("--json", action="store_true")
    b.add_argument("--no-llm", action="store_true")
    r = sub.add_parser("reports", help="tüm raporları zaman-duyarlı doğrula")
    r.add_argument("--zone", default=None)
    d = sub.add_parser("demo-check", help="demo karelerinin beklenen seviyeleri")
    d.add_argument("--no-llm", action="store_true")
    a = ap.parse_args(argv)

    svc = SentinelService(use_llm=not getattr(a, "no_llm", False))
    handlers = {
        "evaluate": cmd_evaluate,
        "batch": cmd_batch,
        "reports": cmd_reports,
        "demo-check": cmd_demo_check,
    }
    return handlers[a.cmd](svc, a)


if __name__ == "__main__":
    sys.exit(main())
