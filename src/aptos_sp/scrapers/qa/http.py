"""QA HTTP client — POST to `apigw.prod.quintoandar.com.br` via
`curl_cffi` chrome impersonation.

The QA frontend hits an internal POST API (`/house-listing-search/v2/`)
that accepts server-side filters. The endpoint is anonymous — no JWT,
no cookies required when called with the same Chrome TLS fingerprint
the browser uses (ADR-012 / curl_cffi). We send the body as JSON,
return parsed JSON.

Auto-disable per ADR-005 §2 still applies: 3 consecutive failures
write a `disabled` row in `runs` and skip QA on subsequent calls.
"""

from typing import Any

from curl_cffi import requests as curl_requests

QA_TIMEOUT_S = 30
QA_IMPERSONATE = "chrome124"

QA_HEADERS: dict[str, str] = {
    "accept": "application/json",
    "accept-language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "content-type": "application/json",
    "origin": "https://www.quintoandar.com.br",
    "referer": "https://www.quintoandar.com.br/",
}


class QaFetchError(RuntimeError):
    """Raised when the QA API returns non-200 or non-JSON. Caller
    decides whether to skip or auto-disable per ADR-005 §2."""


def post_json(url: str, body: dict[str, Any]) -> dict[str, Any]:
    resp = curl_requests.post(
        url,
        json=body,
        headers=QA_HEADERS,
        impersonate=QA_IMPERSONATE,
        timeout=QA_TIMEOUT_S,
    )
    if resp.status_code != 200:
        snippet = resp.text[:200] if resp.text else ""
        raise QaFetchError(f"{url} → HTTP {resp.status_code} (body: {snippet!r})")
    try:
        return resp.json()
    except Exception as e:
        raise QaFetchError(f"{url} → non-JSON body (first 200 chars: {resp.text[:200]!r})") from e
