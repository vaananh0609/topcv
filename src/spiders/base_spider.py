"""
Playwright: chỉ tải HTML — không trích dữ liệu (Parser đảm nhận).
Random User-Agent + delay ngẫu nhiên theo nguồn.
"""

from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from src.core.settings import settings
from src.utils.blocked_html import html_is_waf_blocked
from src.utils.playwright_proxy import get_playwright_proxy
from src.utils.playwright_proxy import get_random_proxy_url

try:
    from curl_cffi import requests as curl_requests
except ImportError:  # pragma: no cover - optional dependency
    curl_requests = None  # type: ignore[assignment]

try:
    from playwright_stealth import Stealth as PlaywrightStealth
except ImportError:  # pragma: no cover - optional dependency
    PlaywrightStealth = None  # type: ignore[misc, assignment]


class BaseSpider(ABC):
    source: str = ""

    @abstractmethod
    def list_url(self) -> str:
        """URL trang danh sách IT."""

    def _delay_range(self) -> tuple[float, float]:
        return (settings.delay_default_min, settings.delay_default_max)

    def _random_user_agent(self) -> str:
        return random.choice(settings.user_agents)

    def _sleep_before_request(self) -> None:
        lo, hi = self._delay_range()
        time.sleep(random.uniform(lo, hi))

    def _proxy_dict(self) -> dict | None:
        return get_playwright_proxy()

    def _should_try_curl_cffi(self, url: str) -> bool:
        if curl_requests is None:
            return False
        host = (urlparse(url).hostname or "").lower()
        if host.endswith("topcv.vn"):
            return bool(settings.topcv_use_curl_cffi_first)
        return False

    def _fetch_via_curl_cffi(self, url: str) -> str:
        timeout = max(5, int(settings.topcv_curl_cffi_timeout_sec))
        impersonate = settings.topcv_curl_cffi_impersonate or "chrome120"
        proxy_url = get_random_proxy_url()
        proxies = None
        if proxy_url:
            proxies = {"http": proxy_url, "https": proxy_url}

        resp = curl_requests.get(  # type: ignore[union-attr]
            url,
            impersonate=impersonate,
            timeout=timeout,
            proxies=proxies,
        )
        resp.raise_for_status()
        return resp.text

    def fetch_html(self, url: str) -> str:
        """GET trang, trả về HTML (có retry)."""
        last_err: Exception | None = None
        for attempt in range(1, settings.crawl_max_retries + 1):
            self._sleep_before_request()
            try:
                return self._fetch_once(url)
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(settings.crawl_retry_backoff_sec * attempt)
        raise last_err  # type: ignore[misc]

    def _fetch_once(self, url: str) -> str:
        if self._should_try_curl_cffi(url):
            try:
                html = self._fetch_via_curl_cffi(url)
                if not html_is_waf_blocked(html):
                    return html
            except Exception:  # noqa: BLE001
                pass

        proxy = self._proxy_dict()
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=settings.playwright_headless,
                proxy=proxy,
            )
            context = browser.new_context(
                user_agent=self._random_user_agent(),
                locale="vi-VN",
            )
            if PlaywrightStealth is not None:
                PlaywrightStealth().apply_stealth_sync(context)
            page = context.new_page()
            page.goto(
                url,
                timeout=settings.playwright_timeout_ms,
                # "load" dễ timeout do ads/tracker; list page chỉ cần DOM chính.
                wait_until="domcontentloaded",
            )
            html = page.content()
            context.close()
            browser.close()
        return html
