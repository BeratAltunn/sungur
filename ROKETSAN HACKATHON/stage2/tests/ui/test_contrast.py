"""Text contrast on every screen stays ≥ 6:1 (the target we adopted from military HMI guidance).

Measured in the browser on the rendered page: each visible text node's colour against its effective background
(ancestor backgrounds and opacity blended). Disabled controls are exempt (WCAG). The one documented exception is
dark ink on the Astro critical fill (#ff3838): the highest ratio that fill allows is ~5.9:1, so ≥ 5.5 is required there.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

MIN = 6.0
MIN_ON_CRITICAL_FILL = 5.5

SCAN = r"""() => {
  const parse = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(',').map(Number); return {r:p[0],g:p[1],b:p[2],a:p.length>3?p[3]:1}; };
  const lum = ({r,g,b}) => { const f = (v) => { v/=255; return v<=0.03928? v/12.92 : Math.pow((v+0.055)/1.055,2.4); }; return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b); };
  const blend = (fg, bg) => ({r: fg.r*fg.a + bg.r*(1-fg.a), g: fg.g*fg.a + bg.g*(1-fg.a), b: fg.b*fg.a + bg.b*(1-fg.a), a: 1});
  const bgOf = (el) => { const stack = []; for (let e = el; e; e = e.parentElement) { const c = parse(getComputedStyle(e).backgroundColor); if (c && c.a > 0) { stack.push(c); if (c.a >= 1) break; } } let bg = parse(getComputedStyle(document.body).backgroundColor); for (const c of stack.reverse()) bg = blend(c, bg); return bg; };
  const out = []; const seen = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const t = walker.currentNode; if (!t.textContent.trim()) continue;
    const el = t.parentElement; if (!el || seen.has(el)) continue; seen.add(el);
    const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
    if (cs.visibility === 'hidden' || cs.display === 'none' || r.width === 0) continue;
    if (el.closest('.sr-only,.skip,.maplibregl-ctrl-attrib,[disabled],:disabled')) continue;
    let op = 1; for (let e = el; e; e = e.parentElement) op *= Number(getComputedStyle(e).opacity);
    const fg = parse(cs.color); if (!fg) continue;
    const bg = bgOf(el); const f = blend({...fg, a: fg.a*op}, bg);
    const L1 = lum(f), L2 = lum(bg); const ratio = (Math.max(L1,L2)+0.05)/(Math.min(L1,L2)+0.05);
    const onCritical = Math.abs(bg.r-255) < 2 && Math.abs(bg.g-56) < 2 && Math.abs(bg.b-56) < 2;
    out.push({text: t.textContent.trim().slice(0,40), cls: String(el.className).slice(0,50), ratio: Math.round(ratio*100)/100, onCritical});
  }
  return out;
}"""

PAGES = [
    ("/#/", ".frame-card"),
    ("/#/frame/img_000860", ".brief .level"),
    ("/#/handover", ".ho-section"),
    ("/#/impact", ".tl-row"),
    ("/#/brief/img_000860", ".card-headline"),
]


def _failures(page: Page) -> list[dict]:
    page.wait_for_timeout(600)  # map markers are added after the map loads
    rows = page.evaluate(SCAN)
    return [r for r in rows if r["ratio"] < (MIN_ON_CRITICAL_FILL if r["onCritical"] else MIN)]


@pytest.mark.parametrize(("path", "ready"), PAGES)
def test_text_contrast(page: Page, path: str, ready: str):
    page.goto(path)
    page.wait_for_selector(ready)
    if path.startswith("/#/frame"):
        page.locator('button.tick[title^="R125"]').click()  # the report card is part of the demo screen
    bad = _failures(page)
    assert bad == [], f"{path}: {len(bad)} metin {MIN}:1 altında: {bad[:8]}"


def test_text_contrast_vehicle_view(page: Page):
    page.add_init_script("localStorage.setItem('map_mode', JSON.stringify('vehicles'))")
    page.goto("/#/")
    page.wait_for_selector(".timebar")
    page.wait_for_selector(".frame-card")  # measured once the card has faded in, as on the frame view
    bad = _failures(page)
    assert bad == [], f"araç görünümü: {len(bad)} metin {MIN}:1 altında: {bad[:8]}"


def test_text_contrast_blind_labelling(page: Page):
    page.add_init_script("localStorage.setItem('labeler', JSON.stringify('contrast'))")
    page.goto("/#/label/img_000860")
    page.wait_for_selector(".image-panel")
    bad = _failures(page)
    assert bad == [], f"#/label: {len(bad)} metin {MIN}:1 altında: {bad[:8]}"
