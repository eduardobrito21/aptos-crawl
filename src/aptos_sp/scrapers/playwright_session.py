"""Playwright sync session with persistent context, per ADR-002.

A single `Session` wraps `sync_playwright`, exposes `goto(url)` with
randomized delays + exponential backoff on 403/429, and is used as a
context manager:

    with Session() as sess:
        for url in urls:
            html = sess.goto(url)

Persistent profile lives at `~/.cache/aptos-sp/playwright-profile/`. If
the profile gets "burned" (challenged on every navigation), the operator
deletes it and Playwright recreates it on next run (ADR-002).

## Cloudflare evasion

ZAP fronts behind Cloudflare. Three layered mitigations:

1. **System Chrome (`channel="chrome"`)** instead of bundled Chromium —
   the TLS/JS fingerprint is what Cloudflare actually expects. Falls
   back to bundled Chromium if Chrome isn't installed.
2. **Automation-flag masking** via `--disable-blink-features=
   AutomationControlled` and an init script that overrides the obvious
   `navigator.webdriver` / `navigator.plugins` tells.
3. **Manual warmup in headed mode** — on the first run, the operator
   solves any interactive Cloudflare challenge; the persistent context
   then carries the proof token (`cf_clearance` cookie) for hours, so
   subsequent headless runs sail through.

If all three still fail, the source is "burned" — delete the profile
directory and try again from a fresh IP / fresh challenge.
"""

import json
import os
import random
import time
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from playwright.sync_api import (
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)

from aptos_sp.config.filters import RateLimit

PROFILE_DIR = Path.home() / ".cache" / "aptos-sp" / "playwright-profile"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
RETRYABLE_STATUSES = {403, 429, 502, 503, 504}

# Patches the most common headless-detection signals. Cloudflare looks
# for `navigator.webdriver === true`, an empty `navigator.plugins`, and
# missing `window.chrome.runtime` — all of which playwright leaves at
# the default detectable values. This script runs before any page JS.
ANTI_DETECTION_INIT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { name: 'Chrome PDF Plugin' },
        { name: 'Chrome PDF Viewer' },
        { name: 'Native Client' },
    ],
});
Object.defineProperty(navigator, 'languages', {
    get: () => ['pt-BR', 'pt', 'en-US', 'en'],
});
window.chrome = window.chrome || { runtime: {} };
"""

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
]


class FetchBlocked(RuntimeError):
    """Raised when a page returns a retryable status after all backoffs
    have been exhausted. Caller decides whether to skip or auto-disable
    the source (ADR-005)."""


class Session:
    def __init__(self, rate_limit: RateLimit, headed: bool | None = None):
        self.rate_limit = rate_limit
        self.headed = headed if headed is not None else os.getenv("HEADED") == "1"
        self._pw: Playwright | None = None
        self._ctx: BrowserContext | None = None
        self._page: Page | None = None

    def __enter__(self) -> Self:
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self._ctx = self._launch_context()
        self._ctx.add_init_script(ANTI_DETECTION_INIT)

        # Always open a fresh page. Reusing `pages[0]` from a restored
        # session can hand back a stale handle that closes during context
        # init, surfacing as `TargetClosedError` on the first goto.
        self._page = self._ctx.new_page()
        for stale in self._ctx.pages:
            if stale is not self._page:
                try:
                    stale.close()
                except Exception:
                    pass
        return self

    def _launch_context(self) -> BrowserContext:
        """Prefer system Chrome (`channel="chrome"`) for a less
        fingerprintable TLS/JS profile; fall back to the bundled
        Chromium if Chrome isn't installed."""
        assert self._pw is not None
        try:
            return self._pw.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                channel="chrome",
                headless=not self.headed,
                user_agent=USER_AGENT,
                viewport={"width": 1440, "height": 900},
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                args=LAUNCH_ARGS,
            )
        except Exception:
            return self._pw.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=not self.headed,
                user_agent=USER_AGENT,
                viewport={"width": 1440, "height": 900},
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                args=LAUNCH_ARGS,
            )

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._ctx is not None:
            self._ctx.close()
        if self._pw is not None:
            self._pw.stop()

    def goto(self, url: str, wait_selector: str | None = None) -> str:
        """Navigate to `url`, return rendered HTML.

        Cloudflare's interactive challenge returns HTTP 403 with HTML
        body — re-navigating doesn't help, the challenge JS has to run
        in-page. We let the page render, watch for the challenge title
        to clear (operator solves it manually in headed mode), and only
        treat the 403 as a real block if the wait window expires.
        """
        assert self._page is not None, "Session not entered"
        delay = self.rate_limit.delay_min_s
        attempt = 0
        while True:
            self._jitter()
            response = self._page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            status = response.status if response else 0

            if self._is_cloudflare_challenge():
                cleared = self._wait_through_challenge()
                if cleared:
                    status = 200  # treat as success; the page is now real

            if status and status in RETRYABLE_STATUSES:
                attempt += 1
                if delay >= self.rate_limit.backoff_max_s:
                    raise FetchBlocked(
                        f"{url} → HTTP {status} after {attempt} retries "
                        f"(likely Cloudflare; try `HEADED=1 uv run scrape` and "
                        f"solve the challenge in the browser window)"
                    )
                time.sleep(delay)
                delay = min(
                    delay * self.rate_limit.backoff_multiplier,
                    self.rate_limit.backoff_max_s,
                )
                continue

            if wait_selector:
                try:
                    self._page.wait_for_selector(wait_selector, timeout=15_000)
                except Exception:
                    # Selector missing is informational, not fatal — the
                    # parser will surface a clearer error than a timeout.
                    pass
            return self._page.content()

    def request_json(self, url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
        """GET a JSON endpoint by navigating the page to it and reading
        the rendered body.

        Why navigation, not `fetch` from a page evaluate:

        - In-page `fetch` is subject to CORS. The browser silently
          strips browser-managed headers (Origin, Referer) and runs a
          preflight against the cross-subdomain target. ZAP's CORS
          config rejects the preflight (or the headers we'd need to
          replicate the real frontend), and fetch throws "Failed to
          fetch" with no usable error.
        - Navigation is not CORS-checked. The browser sends its real
          TLS/cookies to glue-api, Chrome renders the JSON as a plain
          text page, and per-subdomain Cloudflare challenges are
          handled by the same `goto` retry path used for HTML pages.
        - Custom headers are applied with `set_extra_http_headers`,
          which scopes to the whole context. Harmless for other
          requests; equivalent to what the real frontend's interceptors
          inject.
        """
        assert self._page is not None and self._ctx is not None, "Session not entered"
        if headers:
            self._ctx.set_extra_http_headers(headers)
        self.goto(url)
        body = self._page.evaluate(
            "() => document.body.innerText || document.body.textContent || ''"
        )
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            raise FetchBlocked(f"{url} → non-JSON body (first 200 chars: {body[:200]!r})") from e

    def _is_cloudflare_challenge(self) -> bool:
        """Detect via challenge-specific markers.

        Title alone is unreliable — Cloudflare localizes / varies wording
        across challenge variants (JS, managed, Turnstile). A body sniff
        for `challenge-platform` is too broad — it's their bot-detection
        script tag, present on every page they front. The middle ground
        is body markers that ONLY appear during an active challenge:
        the challenge form id, the Turnstile response field, or the
        challenge orchestration path.
        """
        assert self._page is not None
        try:
            title = self._page.title()
        except Exception:
            title = ""
        title_tells = (
            "Just a moment",
            "Attention Required",
            "Please Wait",
            "Um momento",
            "Verificando",  # pt-BR: "Verificando se a conexão é segura"
            "Aguarde",
        )
        if any(t in title for t in title_tells):
            return True
        try:
            body = self._page.content()
        except Exception:
            return False
        body_tells = (
            'id="challenge-form"',
            'name="cf-turnstile-response"',
            "cf-challenge-running",
            "/cdn-cgi/challenge-platform/h/",
            "__cf_chl_",
        )
        return any(t in body for t in body_tells)

    def _wait_through_challenge(self) -> bool:
        """Returns True if the challenge cleared, False if it didn't.

        JS-only challenges resolve in 5–10s. Interactive challenges
        (captcha / Turnstile) only clear with operator help — in headed
        mode we wait up to 5 minutes for that; in headless we give the
        JS challenge ~20s.
        """
        assert self._page is not None
        if self.headed:
            print(
                "  ⚠ Cloudflare challenge — solve it in the browser window. "
                "Waiting up to 5 minutes…",
                flush=True,
            )
        deadline = time.monotonic() + (300 if self.headed else 20)
        while time.monotonic() < deadline:
            time.sleep(2)
            if not self._is_cloudflare_challenge():
                if self.headed:
                    print("  ✓ Challenge cleared, continuing.", flush=True)
                return True
        return False

    def _jitter(self) -> None:
        """Sleep a randomized 2–5s between navigations on the same origin."""
        time.sleep(random.uniform(self.rate_limit.delay_min_s, self.rate_limit.delay_max_s))
