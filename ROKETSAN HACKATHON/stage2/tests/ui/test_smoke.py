"""UI smoke: the demo path (DEMO.md) and the blind-labelling guarantee, in a real browser.

The UI computes no evidence; these tests only check that what the packet says reaches the screen.
"""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

DEMO = "img_000860"
CONTRAST = "img_001733"


def test_triage_queue_and_shift_card(page: Page):
    page.goto("/#/")
    rows = page.locator("li.row")
    expect(rows).to_have_count(40)
    first = rows.first
    expect(first).to_contain_text(DEMO)
    expect(first).to_contain_text("KRİTİK")
    expect(first).to_contain_text(re.compile(r"ETA ~\d+,\d dk"))  # decimal comma, from min_eta_min
    expect(page.locator(".shift")).to_contain_text("YÜKSEK/KRİTİK karar bekliyor")
    # Status bar: facility posture (highest level still waiting) and subsystem health, from the backend.
    expect(page.locator(".posture")).to_contain_text("karar bekliyor")
    expect(page.locator(".classification")).to_contain_text("TASNİF DIŞI")
    # COP: one click selects (preview on the right), the preview opens the frame.
    second = rows.nth(1)
    second_id = second.locator(".row-sub .mono").first.inner_text()
    second.click()
    expect(page.locator(".preview")).to_contain_text(second_id)
    expect(page).to_have_url(re.compile(r"#/$"))
    # Search jumps straight to the contrast frame (DEMO.md 3:20).
    page.get_by_label("Kare ara").fill(CONTRAST[-4:])
    expect(rows).to_have_count(1)
    page.get_by_label("Kare ara").press("Enter")
    expect(page).to_have_url(re.compile(f"#/frame/{CONTRAST}$"))


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
    expect(page.locator("li.row").filter(has_text=DEMO)).to_contain_text("onaylandı")
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
    expect(page.locator("li.row")).to_have_count(0)  # the clock starts before the first frame
    page.get_by_label("Simülasyon saati").fill(str(14 * 60 + 12))
    rows = page.locator("li.row")
    expect(rows.filter(has_text=DEMO)).to_contain_text("YENİ")
    assert 0 < rows.count() < 40
    expect(page.locator(".replay-alert").filter(has_text=DEMO)).to_contain_text("NÖBETÇİ: karar")
    page.get_by_role("button", name="✕ Kapat").click()
    expect(rows).to_have_count(40)
    expect(page.locator(".shift")).to_be_visible()


def test_keyboard_only_operation(page: Page):
    page.goto("/#/")
    expect(page.locator("li.row")).to_have_count(40)
    page.keyboard.press("Tab")
    expect(page.get_by_role("button", name="İçeriğe geç")).to_be_focused()
    # The queue is one Tab stop (roving focus): J moves focus with the cursor, Enter opens the frame.
    rows = page.locator("li.row")
    rows.first.focus()
    page.keyboard.press("j")
    expect(rows.nth(1)).to_be_focused()
    assert rows.nth(0).get_attribute("tabindex") == "-1" and rows.nth(1).get_attribute("tabindex") == "0"
    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(r"#/frame/img_\d+$"))
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
