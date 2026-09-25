"""Precompute detections (and, if an LLM is configured, briefs) for all frames so the demo opens from cache.

    python scripts/precompute.py [--no-llm] [--images img_000860,img_004530]

Also works as the LLM evaluation: how many briefs pass grounding on the first try, after the one
correction round, or fall back to the template, and how long they take.
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sentinel.service import SentinelService  # noqa: E402


def main() -> int:
    use_llm = "--no-llm" not in sys.argv
    only = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--images=")), None)
    svc = SentinelService(use_llm=use_llm)
    print(f"detektör={svc.detector.name}  llm={svc.health()['llm']}")
    frames = [m.image_id for m in svc.repo.frames()] if not only else only.split(",")
    sources: Counter[str] = Counter()
    notes: list[str] = []
    brief_ms: list[float] = []
    t0 = time.perf_counter()
    for img in frames:
        res = svc.evaluate(img, use_llm=use_llm)
        attempts = sum(1 for st in svc.trace(res.run_id) if st["step"].startswith("6_llm"))
        kind = res.brief_source if res.brief_source != "llm" else f"llm ({attempts}. deneme)"
        sources[kind] += 1
        brief_ms.append(res.timings_ms["brief"])
        if res.llm_note:
            notes.append(f"{img}: {res.llm_note}")
        print(
            f"{img}  {res.brief.risk_level.value:<7} {kind:<16} grounding={res.grounding.passed}  "
            f"brief {res.timings_ms['brief'] / 1000:.1f} sn  │ {res.brief.headline[:70]}"
        )
    print(f"\n{len(frames)} kare, {time.perf_counter() - t0:.1f} sn · brief kaynakları {dict(sources)}")
    if brief_ms:
        print(
            f"brief süresi ort {sum(brief_ms) / len(brief_ms) / 1000:.1f} sn, maks {max(brief_ms) / 1000:.1f} sn"
        )
    for n in notes[:10]:
        print(f"  not: {n}")
    print(f"bütçe {svc.budget.status()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
