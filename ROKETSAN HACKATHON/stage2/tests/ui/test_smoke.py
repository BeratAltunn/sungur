"""UI smoke: the demo path (DEMO.md) and the blind-labelling guarantee, in a real browser.

The UI computes no evidence; these tests only check that what the packet says reaches the screen.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from sentinel.config import PROJECT_ROOT

DEMO = "img_000860"
CONTRAST = "img_001733"


FRAMES = ".mk-frame:not(.mk-hidden)"
VEHICLES = ".mk-v:not(.mk-hidden), .mk-vdot:not(.mk-hidden)"


def marker(page: Page, image_id: str):
    return page.locator(f'.mk-frame[data-frame="{image_id}"]')


def flat(page: Page):
    """Compass: back to north-up and no tilt (the main map opens tilted)."""
    page.get_by_role("button", name=re.compile("reset north")).click()
    page.wait_for_timeout(900)


BASE_DISTANCES = """() => {
  const c = (el) => { const r = el.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; };
  const [bx, by] = c(document.querySelector('.mk-base'));
  return [...document.querySelectorAll('.mk-v:not(.mk-hidden)')].map((el) => { const [x, y] = c(el); return Math.hypot(x - bx, y - by); });
}"""
TRUCK = '.mk-v[data-vehicle="T0122"]'  # the demo truck: on screen at the opening time (14:10)


def test_map_is_3d_and_reorients_by_drag_without_moving_points(page: Page):
    page.goto("/#/")
    page.wait_for_function(f"document.querySelectorAll({VEHICLES!r}).length > 20")
    page.keyboard.press("Escape")

    # Opens tilted; vehicle icons stay upright (they face the viewer).
    def tilt(loc) -> float:
        m = re.search(r"rotateX\(([-\d.]+)deg\)", loc.evaluate("(el) => el.style.transform") or "")
        return float(m.group(1)) if m else 0.0

    assert tilt(page.locator(TRUCK)) == 0
    # Flat, then rotate the plane with a right-button drag: every point keeps its distance to the base (the plane
    # turns as one piece; nothing is re-placed), while the view has actually changed.
    flat(page)
    before = page.evaluate(BASE_DISTANCES)
    offsets_before = page.locator(TRUCK).bounding_box()
    vw, vh = page.viewport_size["width"], page.viewport_size["height"]
    page.mouse.move(vw * 0.8, vh * 0.7)
    page.mouse.down(button="right")
    for i in range(1, 11):
        page.mouse.move(vw * 0.8 - 18 * i, vh * 0.7)
    page.mouse.up(button="right")
    page.wait_for_timeout(600)
    after = page.evaluate(BASE_DISTANCES)
    moved = page.locator(TRUCK).bounding_box()
    assert abs(moved["x"] - offsets_before["x"]) + abs(moved["y"] - offsets_before["y"]) > 10  # it rotated
    for d0, d1 in zip(before, after, strict=True):
        assert abs(d1 - d0) < 3, (d0, d1)


def test_triage_map_card_and_shift_card(page: Page):
    page.goto("/#/")
    expect(page.locator(".timebar-tick")).to_have_count(40)
    # The most urgent frame's card is open by default, next to its marker.
    card = page.locator(".frame-card")
    expect(card).to_contain_text(DEMO)
    expect(card).to_contain_text("KRİTİK")
    expect(card).to_contain_text(re.compile(r"~\d+,\d dk"))  # decimal comma, from min_eta_min
    # Motion: the lead vehicle's heading and speed from the backend (T0122, the demo truck).
    expect(card).to_contain_text("T0122")
    expect(card).to_contain_text("km/sa")
    # the top of the map is kept clear: no shift strip, no search/filter box, no view switch (vehicles only)
    expect(page.locator(".shift")).to_have_count(0)
    expect(page.locator(".hud-tools")).to_have_count(0)
    expect(page.get_by_role("group", name="Harita görünümü")).to_have_count(0)
    expect(page.locator(".mk-frame:visible")).to_have_count(0)
    # Status bar: facility posture (highest level still waiting); no banner or subsystem readouts (kept lean).
    expect(page.locator(".posture")).to_contain_text("karar bekliyor")
    expect(page.locator(".topbar")).not_to_contain_text("TASNİF")
    for gone in ("LLM sorgularını kapat", "Bütçe", "D-FINE"):
        expect(page.locator(".topbar")).not_to_contain_text(gone)
    expect(page.locator(".clock")).to_have_count(0)  # no wall clock anywhere
    # COP: a frame's tick on the time bar pins its card; Esc closes it.
    page.locator(f'.timebar-tick[title^="{CONTRAST}"]').click()
    expect(page.locator(".frame-card-pinned")).to_contain_text(CONTRAST)
    expect(page).to_have_url(re.compile(r"#/$"))
    page.keyboard.press("Escape")
    expect(card).to_have_count(0)


def test_markers_stay_anchored_when_zooming(page: Page):
    """Vehicle markers keep their geographic place relative to the base: one zoom step doubles every offset."""
    # ×2 holds only on flat ground; with 3D terrain markers sit at their elevation (test_terrain_* covers that).
    page.add_init_script("localStorage.setItem('terrain', 'false')")
    page.goto("/#/")
    page.wait_for_function(f"document.querySelectorAll({VEHICLES!r}).length > 20")
    page.keyboard.press("Escape")  # card closed: nothing covers the controls
    flat(page)  # zoom scales screen offsets exactly ×2 only on a flat, north-up map
    offsets = """() => {
      const c = (el) => { const r = el.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; };
      const [bx, by] = c(document.querySelector('.mk-base'));
      return [...document.querySelectorAll('.mk-v:not(.mk-hidden)')].map((el) => { const [x, y] = c(el); return [x - bx, y - by]; });
    }"""
    before = page.evaluate(offsets)
    page.get_by_role("button", name="Zoom in").click()
    page.wait_for_timeout(900)  # zoom animation
    after = page.evaluate(offsets)
    for (x0, y0), (x1, y1) in zip(before, after, strict=True):
        assert abs(x1 - 2 * x0) < 3 and abs(y1 - 2 * y0) < 3, (x0, y0, x1, y1)


def test_vehicle_view_plays_the_day_and_the_threshold_thins_it(page: Page):
    """Vehicle view: one marker per vehicle at the clock's time (opening on the most urgent frame's capture time),
    the time bar moves them and the score threshold hides the lower ones. The map shows vehicles only."""
    page.goto("/#/")
    bar = page.locator(".timebar")
    expect(bar).to_be_visible()
    expect(page.locator(".timebar-now")).to_have_text("14:10")  # img_000860, the most urgent frame
    expect(page.locator(".timebar-tick")).to_have_count(40)
    # markers are added once the map has loaded
    page.wait_for_function(f"document.querySelectorAll({VEHICLES!r}).length > 20")
    all_n = page.locator(VEHICLES).count()
    expect(bar).to_contain_text(f"{all_n} araç")  # the bar counts exactly what the map draws
    assert page.evaluate(
        "[...document.querySelectorAll('.mk-frame')].every(e => getComputedStyle(e).display === 'none')"
    )
    # play: the clock runs and the vehicles move
    first = page.locator(".mk-v:not(.mk-hidden)").first
    b0 = first.bounding_box()
    page.get_by_role("button", name="Zamanı oynat").click()
    page.wait_for_timeout(1500)
    page.get_by_role("button", name="Zamanı durdur").click()
    assert page.locator(".timebar-now").inner_text() != "14:10"
    b1 = first.bounding_box()
    assert b0 and b1 and abs(b1["x"] - b0["x"]) + abs(b1["y"] - b0["y"]) > 1
    # a tick jumps to that frame's capture time and opens its card
    page.locator('.timebar-tick[title^="img_000860"]').click()
    expect(page.locator(".timebar-now")).to_have_text("14:10")
    expect(page.locator(".frame-card")).to_contain_text(DEMO)
    # real-time level: the demo truck is KRİTİK at capture (14:10), not yet at 14:05 before its final dash
    truck = page.locator('.mk-v[data-vehicle="T0122"]')
    expect(truck).to_have_class(re.compile(r"\blv-crit\b"))
    page.get_by_role("slider", name="Zaman çubuğu saati").fill("845")
    expect(truck).not_to_have_class(re.compile(r"\blv-crit\b"))
    page.get_by_role("slider", name="Zaman çubuğu saati").fill("850")
    # hovering another frame's vehicle fades in that vehicle's own card (its score, a cut-out of its box), next to it
    other = page.locator(".mk-v:not(.mk-hidden)").evaluate_all(
        "els => els.map(e => [e.dataset.vehicle, (e.title.match(/img_\\d+/) || [''])[0],"
        " (e.title.match(/şu an skor (\\d+)/) || ['', ''])[1], (e.title.match(/çekiminde (\\d+)/) || ['', ''])[1],"
        " [...e.classList].find(c => c.startsWith('lv-'))]).find(([, im]) => im && im !== 'img_000860')"
    )
    assert other, "no vehicle from another frame on screen"
    veh = page.locator(f'.mk-v[data-vehicle="{other[0]}"]')
    veh.dispatch_event("mouseenter")
    card = page.locator(".frame-card-wrap")
    expect(card.locator(".veh-card")).to_be_visible()
    expect(card).to_contain_text(other[1])
    # the head shows the same moment as the marker's colour (clock time 14:10), capture values below it
    expect(card.locator(".frame-card-score")).to_have_text(f"14:10 · skor {other[2]}")
    expect(card.locator(".frame-card-head .level")).to_have_class(re.compile(rf"\b{other[4]}\b"))
    expect(card.locator(".facts")).to_contain_text(f"skor {other[3]}")
    crop = card.locator("img.veh-crop")
    expect(crop).to_have_attribute("src", re.compile(rf"/api/frames/{other[1]}/vehicles/.+/crop$"))
    page.wait_for_function("document.querySelector('img.veh-crop')?.naturalWidth > 0")
    expect(card.locator(".veh-crop-box")).to_be_visible()  # the detection box drawn over the crop
    expect(card).to_have_class(re.compile(r"\bcard-in\b"))
    vb, cbox = veh.bounding_box(), card.bounding_box()
    assert min(abs(cbox["x"] - (vb["x"] + vb["width"])), abs(cbox["x"] + cbox["width"] - vb["x"])) < 80
    veh.dispatch_event("mouseleave")
    expect(card).to_contain_text(DEMO)  # back to the pinned frame
    # threshold: fewer vehicles, all at or above it
    page.get_by_label("Tehdit skoru eşiği").fill("50")
    thinned = page.locator(VEHICLES).count()
    assert 0 < thinned < all_n
    expect(page.locator(".mk-vdot:not(.mk-hidden)")).to_have_count(0)  # unscored tracks hide above 0
    # no frame view to switch to: the map is vehicles only
    expect(page.get_by_role("button", name="Kareler")).to_have_count(0)


def test_terrain_draped_on_main_map_and_can_be_turned_off(page: Page):
    """With tiles installed (scripts/build_terrain.py), the main map loads the local DEM + texture; the operator can
    turn it off (remembered), and the evidence markers are untouched either way."""
    if not (PROJECT_ROOT / "web" / "dist" / "terrain" / "manifest.json").exists():
        pytest.skip("arazi karoları yok: python3 scripts/build_terrain.py")
    tiles: list[int] = []
    page.on(
        "response",
        lambda r: "/terrain/" in r.url and r.url.endswith((".png", ".jpg")) and tiles.append(r.status),
    )
    page.goto("/#/")
    expect(page.locator(FRAMES)).to_have_count(40)
    toggle = page.get_by_role("button", name=re.compile("^Arazi"))
    expect(toggle).to_have_text("Arazi: açık")
    page.wait_for_timeout(600)
    assert tiles and all(s == 200 for s in tiles), tiles  # local tiles only, none missing inside the bounds
    toggle.click()
    expect(toggle).to_have_text("Arazi: kapalı")
    expect(page.locator(FRAMES)).to_have_count(40)  # markers re-added after the style change
    page.reload()
    expect(page.get_by_role("button", name=re.compile("^Arazi"))).to_have_text("Arazi: kapalı")


def test_hover_grows_marker_in_place_and_card_fits(page: Page):
    page.goto("/#/")
    page.wait_for_function(f"document.querySelectorAll({VEHICLES!r}).length > 20")
    page.keyboard.press("Escape")  # the pinned card could cover a marker
    vid = page.evaluate(
        """() => { for (const e of document.querySelectorAll('.mk-v:not(.mk-hidden)')) {
          const r = e.getBoundingClientRect(); const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
          if (top && e.contains(top) && /^T\\d+$/.test(e.dataset.vehicle) && e.title.includes('img_')) return e.dataset.vehicle;
        } return null; }"""
    )
    assert vid, "no uncovered tracked vehicle on screen"
    m = page.locator(f'.mk-v[data-vehicle="{vid}"]')
    before = m.bounding_box()
    m.hover()
    page.wait_for_timeout(150)
    after = m.bounding_box()
    assert after["width"] > before["width"] + 4  # visibly larger
    cx = lambda b: (b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)  # noqa: E731
    (x0, y0), (x1, y1) = cx(before), cx(after)
    assert abs(x1 - x0) < 1.5 and abs(y1 - y0) < 1.5  # still centred on its point
    # The card is placed from its measured height: fully inside the map, even after the thumbnail loads.
    card = page.locator(".frame-card-wrap")
    expect(card).to_contain_text(vid)
    page.locator(".frame-card .preview-img").evaluate("(img) => img.decode().catch(() => {})")
    page.wait_for_timeout(200)
    stage, box = page.locator(".overview-stage").bounding_box(), card.bounding_box()
    assert box["y"] >= stage["y"] and box["y"] + box["height"] <= stage["y"] + stage["height"] + 1
    assert box["x"] >= stage["x"] and box["x"] + box["width"] <= stage["x"] + stage["width"] + 1
    # The map is the page background: the card stays clear of the floating layers above and below it.
    hud_top, hud_bottom = page.locator(".hud-top").bounding_box(), page.locator(".hud-bottom").bounding_box()
    assert box["y"] >= hud_top["y"] + hud_top["height"] and box["y"] + box["height"] <= hud_bottom["y"]


def test_map_is_the_page_background(page: Page):
    page.goto("/#/")
    expect(page.locator(FRAMES)).to_have_count(40)
    vw, vh = page.viewport_size["width"], page.viewport_size["height"]
    bg = page.locator(".map-bg .map").bounding_box()
    assert bg["x"] <= 0 and bg["y"] <= 0 and bg["width"] >= vw and bg["height"] >= vh  # full window
    assert page.evaluate("document.scrollingElement.scrollHeight") <= vh  # nothing scrolls under the map
    # The legend is collapsed by default and opens on demand.
    expect(page.locator(".legend-box .legend")).to_have_count(0)
    page.get_by_role("button", name=re.compile("^Lejant")).click()
    expect(page.locator(".legend-box .legend")).to_contain_text("öncü aracın yönü")


def test_marker_silhouettes_follow_backend_class(page: Page):
    """Each marker draws its frame's lead vehicle class (from /api/map), with the level glyph in the corner."""
    page.goto("/#/")
    expect(page.locator(FRAMES)).to_have_count(40)
    mismatches = page.evaluate(
        """async () => {
          const ctx = await (await fetch('/api/map')).json();
          const out = [];
          for (const f of ctx.frames) {
            const el = document.querySelector(`.mk-frame[data-frame="${f.image_id}"]`);
            const sil = el.querySelector('.veh-sil');
            const got = sil ? [...sil.classList].find((c) => c.startsWith('veh-') && c !== 'veh-sil').slice(4) : null;
            if (got !== f.lead_label) out.push(`${f.image_id}: ${got} != ${f.lead_label}`);
            if (f.lead_label && !el.querySelector('.mk-lv')) out.push(`${f.image_id}: seviye işareti yok`);
          }
          return out;
        }"""
    )
    assert mismatches == []
    expect(marker(page, DEMO).locator(".mk-lv")).to_have_text("▲▲")


def test_card_fades_in_and_out_on_hover(page: Page):
    page.goto("/#/")
    card = page.locator(".frame-card-wrap")
    expect(card).to_contain_text(DEMO)  # the pinned (most urgent) frame
    marker(page, CONTRAST).dispatch_event("mouseenter")
    expect(page.locator(".frame-card-wrap.card-in")).to_contain_text(CONTRAST)
    marker(page, CONTRAST).dispatch_event("mouseleave")
    expect(page.locator(".frame-card-wrap.card-out")).to_contain_text(CONTRAST)  # fades out first…
    # …then the pinned card fades back in
    expect(page.locator(".frame-card-wrap.card-in")).to_contain_text(DEMO)
    expect(card).to_have_count(1)


def test_demo_frame_aha_moment(page: Page):
    page.goto(f"/#/frame/{DEMO}")
    expect(page.locator(".brief .level")).to_contain_text("KRİTİK")
    # 12:35 ✗ on the time slider → the report card with the verifier's reason (DEMO.md 2:00).
    page.locator('button.tick[title^="R125"]').click()
    card = page.locator(".callout")
    expect(card).to_contain_text("ÇELİŞİYOR")
    expect(card).to_contain_text("12:35")
    expect(card).to_contain_text("T0122")
    expect(page.locator(".slider-now")).to_contain_text("12:35")
    # 12:25 ✗: identity claim.
    page.locator('button.tick[title^="R119"]').click()
    expect(card).to_contain_text("kimlik iddiası")
    expect(card).to_contain_text("ÇELİŞİYOR")


def test_frame_map_shows_zones_grid_and_picked_tracks(page: Page):
    """Frame page map: every zone name and the faint grid as on the main map; the operator picks which tracks show."""
    page.goto(f"/#/frame/{DEMO}")
    fmap = page.locator(".frame-map")
    # reports tab: just the count, no verdict symbols
    n_reports = len(page.request.get(f"/api/frames/{DEMO}/packet").json()["reports"])
    expect(page.get_by_role("tab", name=re.compile("^Raporlar"))).to_have_text(f"Raporlar ({n_reports})")
    n_zones = len(page.request.get("/api/map").json()["zones"])
    expect(fmap.locator(".mk-zone")).to_have_count(n_zones)
    expect(fmap.locator(".mk-zone-active")).to_have_count(1)
    truck = fmap.locator('.mk-veh[title~="T0122"]')
    expect(truck).to_be_visible()
    # same symbols and view as the main map: class silhouette in the level colour, tiltable 3D plane
    expect(truck.locator(".mk-v .veh-sil")).to_have_count(1)
    expect(fmap.locator(".maplibregl-ctrl-compass")).to_have_count(1)
    picker = fmap.get_by_role("button", name=re.compile(r"^İzler"))
    total = int(re.search(r"/(\d+)", picker.inner_text()).group(1))
    picker.click()
    box = fmap.get_by_role("group", name="Gösterilecek izler")
    box.get_by_role("checkbox", name=re.compile(r"T0122")).uncheck()
    expect(truck).to_be_hidden()
    expect(picker).to_contain_text(f"{total - 1}/{total}")
    box.get_by_role("button", name="Hiçbiri").click()
    expect(fmap.locator(".mk-veh:visible")).to_have_count(0)
    box.get_by_role("button", name="Tümü").click()
    expect(truck).to_be_visible()
    expect(picker).to_contain_text(f"{total}/{total}")


def test_live_run_streams_six_steps(page: Page):
    page.goto(f"/#/frame/{DEMO}")
    expect(page.locator(".brief .level")).to_be_visible()
    page.get_by_role("button", name=re.compile("Canlı yeniden değerlendir")).click()
    expect(page.get_by_role("tab", name="Ajan izi")).to_have_attribute("aria-selected", "true")
    expect(page.locator(".toast")).to_contain_text("Canlı değerlendirme tamamlandı", timeout=30_000)
    trace = page.locator(".trace")
    for step in ("1 · Tespit", "3 · Eşleme ve kinematik", "4 · Rapor doğrulama", "5 · Risk"):
        expect(trace).to_contain_text(step)
    expect(trace).to_contain_text("çelişen R119, R125")  # readable step summary, from the trace record
    expect(page.locator(".brief .level")).to_contain_text("KRİTİK")


def test_decision_shows_in_queue_and_next_pending(page: Page):
    page.goto(f"/#/frame/{DEMO}")
    expect(page.locator(".brief .level")).to_be_visible()
    page.get_by_role("button", name=re.compile("^Onayla")).click()
    expect(page.locator(".decision")).to_contain_text("onaylandı")
    page.get_by_role("button", name=re.compile("Sonraki bekleyen")).click()
    expect(page).not_to_have_url(re.compile(f"#/frame/{DEMO}$"))
    page.goto("/#/")
    expect(page.locator(".frame-card")).to_contain_text(DEMO)  # still the most urgent frame
    expect(page.locator(".frame-card")).to_contain_text("onaylandı")
    # Undo (a new record, never a delete) clears it again.
    page.goto(f"/#/frame/{DEMO}")
    page.get_by_role("button", name="Geri al").click()
    expect(page.locator(".decision")).not_to_contain_text("onaylandı")


def test_escalation_card_and_shift_handover(page: Page):
    page.goto(f"/#/frame/{DEMO}")
    expect(page.locator(".brief .level")).to_be_visible()
    page.get_by_role("button", name=re.compile("^Amire ilet")).click()
    page.get_by_role("link", name=re.compile("Eskalasyon kartı")).click()
    expect(page).to_have_url(re.compile(f"#/brief/{DEMO}$"))
    expect(page.locator(".card-page")).to_contain_text("amire iletildi")
    expect(page.locator(".card-page")).to_contain_text("R125")  # contradicted reports are on the card
    page.goto("/#/handover")
    escalated = page.locator(".ho-section").filter(has_text="Amire iletilenler")
    expect(escalated).to_contain_text(DEMO)
    expect(page.locator(".ho-section").filter(has_text="resmî raporlar")).to_contain_text("R119")
    page.goto(f"/#/frame/{DEMO}")
    page.get_by_role("button", name="Geri al").click()
    expect(page.locator(".decision")).not_to_contain_text("amire iletildi")


def test_impact_view_and_shift_replay(page: Page):
    page.goto("/#/impact")
    expect(page.locator(".tile").first).to_contain_text("KRİTİK: karar araç varmadan önce")
    expect(page.locator(".params")).to_contain_text("varsayım")  # no measurements in a fresh run dir
    expect(page.locator(".tl-row").filter(has_text=DEMO)).to_contain_text("NÖBETÇİ")
    # Replay: frames join the queue at their capture time.
    page.get_by_role("link", name=re.compile("Vardiyayı oynat")).click()
    expect(page.locator(".replay")).to_be_visible()
    frames = page.locator(FRAMES)
    expect(frames).to_have_count(0)  # the clock starts before the first frame
    page.get_by_label("Simülasyon saati").fill(str(14 * 60 + 12))
    expect(marker(page, DEMO)).to_have_class(re.compile(r"\bmk-new\b"))
    assert 0 < frames.count() < 40
    expect(page.locator(".replay-alert").filter(has_text=DEMO)).to_contain_text("NÖBETÇİ: karar")
    page.get_by_role("button", name="✕ Kapat").click()
    expect(frames).to_have_count(40)
    expect(page.locator(".replay")).to_have_count(0)


def test_keyboard_only_operation(page: Page):
    page.goto("/#/")
    card = page.locator(".frame-card")
    expect(card).to_contain_text(DEMO)  # the most urgent frame is selected
    page.keyboard.press("Tab")
    expect(page.get_by_role("button", name="İçeriğe geç")).to_be_focused()
    # J/K walk the frames in risk order (the card follows), Enter opens the selected one.
    page.keyboard.press("j")
    expect(card).not_to_contain_text(DEMO)
    nxt = card.locator(".preview-id .mono").inner_text()
    page.keyboard.press("k")
    expect(card).to_contain_text(DEMO)
    page.keyboard.press("j")
    expect(card).to_contain_text(nxt)
    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(rf"#/frame/{nxt}$"))
    # Evidence tabs follow the WAI-ARIA tabs pattern (←/→).
    page.get_by_role("tab", name="Neden?").focus()
    page.keyboard.press("ArrowRight")
    expect(page.get_by_role("tab", name=re.compile("^Raporlar"))).to_have_attribute("aria-selected", "true")
    expect(page.get_by_role("tabpanel")).to_be_visible()


def test_errors_are_operational(page: Page):
    """A failing service shows what happened and what to do, not a raw HTTP status line."""
    page.route("**/api/handover", lambda route: route.fulfill(status=500, body="boom"))
    page.goto("/#/handover")
    alert = page.get_by_role("alert")
    expect(alert).to_contain_text("Servis bu isteği tamamlayamadı")
    expect(alert).to_contain_text("Tekrar dene")
    expect(alert).not_to_contain_text("Internal Server Error")


def test_blind_labelling_never_shows_system_level(page: Page):
    page.add_init_script("localStorage.setItem('labeler', JSON.stringify('ui-smoke'))")
    page.goto(f"/#/label/{DEMO}")
    expect(page.locator(".image-panel")).to_be_visible()
    page.locator('button.tick[title^="R125"]').click()
    expect(page.locator(".callout")).to_be_visible()  # report verdicts are evidence; levels are not
    leaks = page.evaluate(
        """() => {
          const out = [];
          // Level classes may only appear on the labeller's own level picker.
          document.querySelectorAll('[class*="lv-"]').forEach((el) => {
            if (!el.closest('.label-levels')) out.push('sınıf: ' + el.className);
          });
          for (const sel of ['.brief', '.score', '.why', '.chat', '.chat-fab']) {
            if (document.querySelector(sel)) out.push('öğe: ' + sel);
          }
          // Compare as computed rgb() so a hex attribute and a CSS variable of the same colour count once.
          const norm = (c) => { const i = document.createElement('i'); i.style.color = c; document.body.appendChild(i); const v = getComputedStyle(i).color; i.remove(); return v; };
          const colours = new Set();
          document.querySelectorAll('.box rect').forEach((r) => colours.add(norm(r.getAttribute('stroke'))));
          document.querySelectorAll('.mk-veh.mk-vehicle').forEach((m) => colours.add(norm(m.style.getPropertyValue('--c'))));
          document.querySelectorAll('.map-legend .sym-legend path').forEach((p) => colours.add(getComputedStyle(p).fill));
          if (colours.size > 1) out.push('renkler: ' + [...colours].join(','));
          return out;
        }"""
    )
    assert leaks == [], f"kör modda sistem çıktısı sızıyor: {leaks}"
    expect(page.locator(".posture")).to_have_count(0)  # the status bar posture would reveal levels


def test_drag_vehicle_into_chat_changes_the_questions(page: Page):
    page.goto(f"/#/frame/{DEMO}")
    expect(page.locator(".brief .level")).to_be_visible()
    page.get_by_role("button", name=re.compile("^Sohbet")).click()
    quick = page.locator(".quick .suggestion")
    expect(quick.first).to_be_visible()  # situation questions for the open frame, before any question
    chip = page.locator(".col-left .vchip").filter(has_text="T0122")
    ref = chip.locator("b").inner_text()  # V-number of the truck's track in this run
    chip.drag_to(page.locator(".chat"))
    expect(page.locator(".chat-context")).to_contain_text("T0122")
    expect(quick.first).to_contain_text("T0122")  # the questions were refetched for the dragged vehicle
    for q in quick.all_inner_texts():
        assert "T0122" in q or ref in q, q  # every question is about that vehicle
    first = quick.first.locator(".quick-text").inner_text()
    page.keyboard.press("Alt+1")  # quick question from the keyboard, even with the cursor in the text box
    expect(page.locator(".msg-user").last).to_contain_text(first)
    expect(page.locator(".msg-user").last).to_contain_text("T0122")  # the question carried the vehicle
    expect(page.locator(".msg-bot").last).to_contain_text("Kayıtlara göre")
    expect(page.get_by_label("Sıradaki sorular")).to_be_visible()  # follow-ups keep the loop going
    assert first not in page.locator(".quick").inner_text()
    page.get_by_role("button", name=f"{ref} · T0122 bağlamdan çıkar").click()
    expect(page.locator(".chat-context")).not_to_contain_text("T0122")


def test_two_alert_cards_in_the_chat_ask_to_compare(page: Page):
    page.goto("/#/")
    rail = page.locator(".rail")
    rows = rail.locator(".rail-card")  # the alert rail floating on the map: pending YÜKSEK/KRİTİK frames
    expect(rows.first).to_be_visible()
    page.get_by_role("button", name=re.compile("^Sohbet")).click()
    chat = page.locator(".chat")
    a = rows.nth(0).locator(".row-sub .mono").first.inner_text()
    b = rows.nth(1).locator(".row-sub .mono").first.inner_text()
    # drag by the id line (a button inside the card cannot start a drag)
    rows.nth(0).locator(".row-sub").drag_to(chat)
    rail.hover()  # the rail fades back when the pointer leaves it; a user hovers it again before the next drag
    rows.nth(1).locator(".row-sub").drag_to(chat)
    ctx = page.locator(".chat-context")
    expect(ctx).to_contain_text(a)
    expect(ctx).to_contain_text(b)
    first = page.locator(".quick .suggestion").first
    expect(first).to_contain_text(a)  # the questions now connect the two frames
    expect(first).to_contain_text(b)
    # the same card again is not added twice; "Sor" on a card is the no-drag way in
    rail.hover()
    rows.nth(0).locator(".row-sub").drag_to(chat)
    expect(ctx.locator(".ctx-pill")).to_have_count(2)
    page.get_by_role("button", name=f"{b} bağlamdan çıkar").click()
    expect(ctx).not_to_contain_text(b)
    rail.hover()  # at rest the rail is a faded single line per alert; hovering brings its buttons back
    rail.get_by_role("button", name=f"{b} karesini sohbete ekle").click()
    expect(ctx).to_contain_text(b)


def test_chat_box_completes_locally_without_requests(page: Page):
    calls: list[str] = []
    page.on("request", lambda r: calls.append(r.url) if "/api/chat" in r.url else None)
    page.goto(f"/#/frame/{DEMO}")
    expect(page.locator(".brief .level")).to_be_visible()
    page.get_by_role("button", name=re.compile("^Sohbet")).click()
    box = page.get_by_role("combobox", name="Soru")
    expect(page.locator(".quick .suggestion").first).to_be_visible()
    before = len(calls)
    box.press_sequentially("T01 ")  # a space closes the word: no list
    box.fill("")
    box.press_sequentially("T01")
    ac = page.locator(".ac")
    expect(ac.locator(".ac-item").first).to_contain_text("T0122")  # the open frame's track first
    box.press("Tab")
    expect(box).to_have_value("T0122 ")
    box.press_sequentially("dog")
    expect(ac).to_contain_text("Doğu Yolu")  # zones, diacritics ignored
    box.press("Tab")
    expect(box).to_have_value("T0122 Doğu Yolu ")
    box.press_sequentially("12:3")
    expect(ac).to_contain_text("12:35")
    box.press("Escape")  # closes the list, not the chat
    expect(ac).to_have_count(0)
    expect(page.locator(".chat")).to_be_visible()
    # typing asked nothing: no chat request, and the vocabulary was loaded once
    assert not any(u.endswith("/api/chat") for u in calls[before:]), calls
    assert sum("/api/chat/vocab" in u for u in calls) == 1, calls
