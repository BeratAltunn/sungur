"""Browser smoke tests: the built UI (web/dist) against a real API server (oracle detector, mock LLM).

Skipped when Playwright or a Chromium browser is missing (e.g. inside Docker) or the UI is not built.
Uses the system Chrome (channel="chrome") so no browser download is needed; falls back to Playwright's
bundled Chromium if that is installed.

    make ui-test        (needs: pip install playwright, Google Chrome, cd web && npm run build)
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request

import pytest

from sentinel.agent.llm import MockLLM
from sentinel.config import PROJECT_ROOT
from sentinel.interfaces import api
from sentinel.service import SentinelService

sync_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright kurulu değil (pip install playwright)"
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def base_url(settings, tmp_path_factory):
    import uvicorn

    if not (PROJECT_ROOT / "web" / "dist" / "index.html").exists():
        pytest.skip("arayüz derlenmemiş: cd web && npm run build")
    s = settings.model_copy(deep=True)  # own decision log: UI tests record decisions
    s.observability.runs_dir = tmp_path_factory.mktemp("ui-runs")
    s.observability.labels_dir = tmp_path_factory.mktemp("ui-labels")
    api.service_factory = lambda: SentinelService(s, llm=MockLLM())
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(api.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 60
    while True:  # server up and the warm-up done (the queue shows every frame)
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=2) as r:
                w = json.load(r)["warmup"]
                if w["total"] and w["done"] == w["total"]:
                    break
        except OSError:
            pass
        if time.time() > deadline:
            pytest.fail("API sunucusu 60 sn içinde hazır olmadı")
        time.sleep(0.3)
    yield url
    server.should_exit = True
    thread.join(timeout=10)
    api.service_factory = SentinelService


@pytest.fixture(scope="session")
def browser():
    with sync_api.sync_playwright() as p:
        b = None
        for kwargs in ({"channel": "chrome"}, {}):
            try:
                b = p.chromium.launch(**kwargs)
                break
            except Exception:  # noqa: BLE001 - no such browser on this machine
                continue
        if b is None:
            pytest.skip("Chromium/Chrome bulunamadı (Google Chrome kurun ya da: playwright install chromium)")
        yield b
        b.close()


@pytest.fixture
def page(browser, base_url):
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, base_url=base_url)
    pg = ctx.new_page()
    # The main map opens in vehicle view; these tests cover the frame view unless they switch (a later init
    # script wins).
    pg.add_init_script("localStorage.setItem('map_mode', JSON.stringify('frames'))")
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.errors = errors  # type: ignore[attr-defined]
    yield pg
    ctx.close()
    assert not errors, f"sayfada yakalanmamış JS hatası: {errors}"
