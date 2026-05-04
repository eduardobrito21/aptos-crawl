"""Direct `glue-api` client using `curl_cffi` for TLS fingerprint
impersonation.

Cloudflare's bot detection inspects TLS / JA3 / HTTP/2 frame ordering —
not just headers. A real Chrome TLS handshake passes; Python's stdlib
ssl + httpx do not, regardless of how careful we are with headers.
`curl_cffi` wraps curl-impersonate, which sends Chrome's exact wire
fingerprint, and is the standard fix when CF returns hard 403s with no
challenge UI.

This client replaces the Playwright-based path for ZAP's listings API
(see ADR-012). Playwright stays in the project for any future
detail-page scraping that genuinely needs JS rendering.
"""

from typing import Any

from curl_cffi import requests as curl_requests

# Chrome version Playwright reports varies; this just needs to be a
# fingerprint curl-impersonate ships. `chrome124` is current as of
# this writing and accepted by Cloudflare's edge.
IMPERSONATE = "chrome124"
TIMEOUT_S = 30


class FetchBlocked(RuntimeError):
    """Raised when glue-api returns non-200 or non-JSON. Caller decides
    whether to skip or auto-disable the source (ADR-005)."""


def fetch_json(url: str, *, headers: dict[str, str]) -> dict[str, Any]:
    """GET a JSON URL, return parsed body."""
    full_headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        **headers,
    }
    resp = curl_requests.get(
        url,
        headers=full_headers,
        impersonate=IMPERSONATE,
        timeout=TIMEOUT_S,
    )
    if resp.status_code != 200:
        snippet = resp.text[:200] if resp.text else ""
        raise FetchBlocked(f"{url} → HTTP {resp.status_code} (body starts: {snippet!r})")
    try:
        return resp.json()
    except Exception as e:
        raise FetchBlocked(f"{url} → non-JSON body (first 200 chars: {resp.text[:200]!r})") from e
