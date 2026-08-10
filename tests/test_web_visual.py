"""Headless-browser smoke tests for the dashboard (optional).

These run the real JS stack (Tailwind browser build, Alpine, uPlot) against a
live uvicorn server, catching the class of bugs unit tests cannot: missing
script tags in templates, wrong vendor-build loading, uPlot option contract
violations (e.g. fmtDate must return a function).

They SKIP when playwright or its chromium binary is not installed, so CI and
fresh clones are unaffected:

    uv add --dev playwright && uv run playwright install chromium
    uv run pytest tests/test_web_visual.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest


pytest.importorskip("playwright", reason="playwright not installed")

from playwright.sync_api import sync_playwright  # noqa: E402


APP_DIR = Path(__file__).resolve().parent.parent
PORT = 8931


@pytest.fixture(scope="module")
def server():
    """Boot the real app on a scratch port for the duration of the module."""
    import os

    env = dict(os.environ)
    env["GARMINDASH_PORT"] = str(PORT)  # unused by uvicorn; keep for clarity
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.app:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=APP_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # wait for /healthz
        import urllib.request

        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/healthz", timeout=1)
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("server did not start")
        yield PORT
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            yield b
            b.close()
    except Exception as e:  # browser binary missing
        pytest.skip(f"chromium binary unavailable: {e}")


def _visit(page, url: str) -> list[str]:
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on(
        "console",
        lambda m: errors.append(f"console: {m.text}") if m.type == "error" else None,
    )
    page.goto(url, wait_until="networkidle")
    page.wait_for_timeout(2500)  # let Tailwind browser build + Alpine finish
    return errors


def test_today_page_loads_design_and_data(browser, server):  # noqa: ARG001
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = _visit(page, f"http://127.0.0.1:{PORT}/?date=2026-08-09")
    assert errors == [], errors
    # Tailwind browser build applied: body must be dark (zinc-950)
    bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
    assert bg not in ("rgba(0, 0, 0, 0)", "rgb(255, 255, 255)"), f"body bg {bg}"
    # three-column card grid renders
    assert page.evaluate("document.querySelectorAll('main > div.grid > div').length") == 3
    # dial is rotated to start at 12 o'clock and shows the score
    assert page.evaluate('getComputedStyle(document.querySelector("svg")).rotate') == "-90deg"
    assert page.evaluate('document.body.textContent.includes("Herstel")')
    page.close()


def test_trends_charts_render(browser, server):  # noqa: ARG001
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = _visit(page, f"http://127.0.0.1:{PORT}/trends")
    assert errors == [], errors
    sizes = page.evaluate(
        """[...document.querySelectorAll("[id^=chart-]")].map(el => {
            const c = el.querySelector("canvas");
            return c ? c.getBoundingClientRect().width : 0;
        })"""
    )
    assert len(sizes) == 5
    # canvases must be laid out (not the 300px default before CSS applied)
    assert all(w > 400 for w in sizes), sizes
    page.close()


def test_intraday_chart_draws_and_navigates(browser, server):  # noqa: ARG001
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = _visit(page, f"http://127.0.0.1:{PORT}/intraday?date=2026-08-09")
    assert errors == [], errors
    # Alpine must have processed the page (x-data stack attached)
    assert page.evaluate('!!document.querySelector("[x-data]")._x_dataStack')
    # chart canvas exists and has painted pixels
    painted = page.evaluate(
        """(() => {
            const c = document.querySelector("#chart-intraday canvas");
            if (!c) return false;
            return c.getContext("2d").getImageData(0, 0, 100, 100).data
                    .some((v, i) => i % 4 === 3 && v > 0);
        })()"""
    )
    assert painted
    # day navigation via the date input still renders a chart
    page.evaluate(
        """(() => {
            const i = document.querySelector('input[type=date]');
            i.value = '2026-08-10';
            i.dispatchEvent(new Event('change'));
        })()"""
    )
    page.wait_for_timeout(2000)
    assert page.evaluate('!!document.querySelector("#chart-intraday canvas")')
    page.close()
