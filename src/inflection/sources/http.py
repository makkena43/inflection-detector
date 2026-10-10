"""Rate-limited stdlib HTTP client shared by the exchange adapters.

* one request at a time per client, at least ``min_interval`` seconds apart;
* network errors and 5xx are retried with exponential backoff;
* 401/403/429 are never retried: the window is reported BLOCKED (spec section 22).

``transport`` can be replaced in tests; it takes (url, headers, timeout) and returns
(status, body) or raises ``OSError`` for a network failure.
"""

from __future__ import annotations

import http.cookiejar
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36")
BLOCKING_STATUSES = frozenset({401, 403, 429})

Transport = Callable[[str, dict, float], tuple[int, bytes]]


@dataclass(frozen=True)
class Response:
    url: str
    status: Optional[int]       # None when no HTTP response arrived
    body: bytes = b""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == 200

    @property
    def blocked(self) -> bool:
        return self.status in BLOCKING_STATUSES


def _urllib_transport() -> Transport:
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def send(url: str, headers: dict, timeout: float) -> tuple[int, bytes]:
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, b""

    return send


def curl_cffi_transport(impersonate: str = "chrome") -> Transport:
    """Transport backed by curl_cffi with a browser TLS/HTTP2 fingerprint.

    Defense-in-depth for BSE's Akamai edge (header checks already handled by callers);
    keeps one ``Session`` so cookies persist across calls.
    Raises ``ImportError`` when curl_cffi is not installed.
    """
    from curl_cffi import requests as cffi_requests

    session = cffi_requests.Session(impersonate=impersonate)

    def send(url: str, headers: dict, timeout: float) -> tuple[int, bytes]:
        try:
            r = session.get(url, headers=headers, timeout=timeout)
        except Exception as exc:  # curl_cffi errors are not OSError subclasses
            raise OSError(f"{type(exc).__name__}: {exc}") from exc
        return r.status_code, r.content

    return send


class HttpClient:
    def __init__(self, min_interval: float = 1.0, retries: int = 3, backoff: float = 2.0, timeout: float = 40.0,
                 transport: Optional[Transport] = None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic, user_agent: str = USER_AGENT):
        self.min_interval, self.retries, self.backoff, self.timeout = min_interval, retries, backoff, timeout
        self._send = transport or _urllib_transport()
        self._sleep, self._clock, self.user_agent = sleep, clock, user_agent
        self._last: Optional[float] = None
        self.requests = 0

    def _pace(self) -> None:
        if self._last is not None:
            wait = self.min_interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()

    def get(self, url: str, referer: str = "", accept: str = "application/json, text/plain, */*",
            origin: str = "", extra_headers: Optional[dict] = None) -> Response:
        headers = {"User-Agent": self.user_agent, "Accept": accept}
        if referer:
            headers["Referer"] = referer
        if origin:
            headers["Origin"] = origin
        if extra_headers:
            headers.update(extra_headers)
        last = Response(url, None, error="not attempted")
        for attempt in range(self.retries + 1):
            if attempt:
                self._sleep(self.backoff * 2 ** (attempt - 1))
            self._pace()
            self.requests += 1
            try:
                status, body = self._send(url, headers, self.timeout)
            except OSError as exc:
                last = Response(url, None, error=f"{type(exc).__name__}: {exc}")
                continue
            last = Response(url, status, body)
            if status < 500:
                return last
        return last
