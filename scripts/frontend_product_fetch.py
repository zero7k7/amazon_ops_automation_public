from __future__ import annotations

import contextlib
import http.client
import importlib.util
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable


LocationLoader = Callable[[], dict[str, dict[str, str]]]
TextCleaner = Callable[[object], str]


STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['en-GB', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
window.chrome = window.chrome || {};
window.chrome.runtime = window.chrome.runtime || {};
const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
if (originalQuery) {
  window.navigator.permissions.query = (parameters) => (
    parameters && parameters.name === 'notifications'
      ? Promise.resolve({ state: Notification.permission })
      : originalQuery(parameters)
  );
}
"""


def fetch_html_urllib(url: str, timeout: int, *, user_agent: str) -> tuple[str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept-Language": "en-GB,en;q=0.9,de;q=0.8,zh-CN;q=0.7",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace"), ""
    except (urllib.error.URLError, TimeoutError, OSError, http.client.IncompleteRead) as exc:
        return "", str(exc)


def visible_delivery_location(page, *, clean_location_text: TextCleaner) -> str:
    selectors = [
        "#glow-ingress-line2",
        "#contextualIngressPtLabel_deliveryShortLine",
        "#nav-global-location-popover-link",
    ]
    for selector in selectors:
        with contextlib.suppress(Exception):
            text = clean_location_text(page.locator(selector).first.inner_text(timeout=2500))
            text = re.sub(r"^Deliver to\s+", "", text, flags=re.I).strip()
            if text:
                return text
    return ""


def apply_delivery_location(
    page,
    marketplace: str,
    postcode: str,
    *,
    clean_location_text: TextCleaner,
) -> str:
    if not postcode:
        return "未配置配送邮编"
    marketplace_key = str(marketplace or "").strip().upper()
    try:
        trigger = page.locator("#nav-global-location-popover-link, #glow-ingress-block").first
        trigger.click(timeout=5000)
        zip_input = page.locator("#GLUXZipUpdateInput").first
        zip_input.fill(postcode, timeout=8000)
        page.locator("#GLUXZipUpdate").first.click(timeout=5000)
        with contextlib.suppress(Exception):
            page.locator("#GLUXConfirmClose, input[name='glowDoneButton']").first.click(timeout=5000)
        page.wait_for_timeout(1800)
        page.reload(wait_until="domcontentloaded", timeout=20000)
        with contextlib.suppress(Exception):
            page.wait_for_load_state("networkidle", timeout=4000)
        visible_location = visible_delivery_location(page, clean_location_text=clean_location_text)
        if visible_location and postcode.lower() in visible_location.lower():
            return f"{marketplace_key} {postcode} 已设置"
        if visible_location:
            return visible_location
        return f"{marketplace_key} {postcode} 未确认：未读取到页面顶部配送地区"
    except Exception as exc:
        visible_location = visible_delivery_location(page, clean_location_text=clean_location_text)
        if visible_location:
            return visible_location
        return f"{marketplace_key} {postcode} 未确认：{exc}"


def launch_chromium(p, use_chrome: bool):
    options = {
        "headless": True,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        "ignore_default_args": ["--enable-automation"],
    }
    if use_chrome:
        options["channel"] = "chrome"
    return p.chromium.launch(**options)


def install_stealth_init(context) -> None:
    with contextlib.suppress(Exception):
        context.add_init_script(STEALTH_INIT_SCRIPT)


def launch_persistent_chromium_context(
    p,
    *,
    user_data_dir: Path,
    use_chrome: bool,
    locale: str,
    timezone_id: str,
    user_agent: str,
    headless: bool = False,
):
    user_data_dir.mkdir(parents=True, exist_ok=True)
    options = {
        "headless": headless,
        "user_agent": user_agent,
        "locale": locale,
        "timezone_id": timezone_id,
        "viewport": {"width": 1365, "height": 1800},
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        "ignore_default_args": ["--enable-automation"],
    }
    if use_chrome:
        options["channel"] = "chrome"
    context = p.chromium.launch_persistent_context(str(user_data_dir), **options)
    install_stealth_init(context)
    return context


class FrontendBrowserSession:
    def __init__(
        self,
        *,
        user_agent: str,
        profile_root: Path,
        load_locations: LocationLoader,
        clean_location_text: TextCleaner,
        use_chrome: bool = False,
        persistent: bool = False,
        headless: bool = False,
        apply_location: bool = True,
        apply_delivery_location_func: Callable[..., str] | None = None,
        launch_chromium_func: Callable[..., object] | None = None,
    ):
        self.user_agent = user_agent
        self.use_chrome = use_chrome
        self.persistent = persistent
        self.profile_root = profile_root
        self.headless = headless
        self.apply_location = apply_location
        self.clean_location_text = clean_location_text
        self.apply_delivery_location_func = apply_delivery_location_func or apply_delivery_location
        self.launch_chromium_func = launch_chromium_func or launch_chromium
        self._playwright_manager = None
        self._browser = None
        self._contexts: dict[str, object] = {}
        self._location_notes: dict[str, str] = {}
        self._locations = load_locations()

    def _ensure_playwright(self):
        if self._playwright_manager is not None:
            return self._playwright_manager
        if not importlib.util.find_spec("playwright"):
            raise RuntimeError("Playwright 未安装")
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # pragma: no cover - optional dependency guard
            raise RuntimeError(f"Playwright 不可用：{exc}") from exc
        self._playwright_manager = sync_playwright().start()
        return self._playwright_manager

    def _ensure_browser(self):
        if self._browser is not None:
            return self._browser
        if self.persistent:
            raise RuntimeError("持久 Chrome 会话不使用共享 browser 对象")
        self._ensure_playwright()
        self._browser = self.launch_chromium_func(self._playwright_manager, self.use_chrome)
        return self._browser

    def get_context(self, marketplace: str):
        marketplace_key = str(marketplace or "").strip().upper()
        context = self._contexts.get(marketplace_key)
        if context is not None:
            return context
        location = self._locations.get(marketplace_key, {})
        if self.persistent:
            manager = self._ensure_playwright()
            context = launch_persistent_chromium_context(
                manager,
                user_data_dir=self.profile_root / marketplace_key.lower(),
                use_chrome=self.use_chrome,
                locale=location.get("locale") or "en-GB",
                timezone_id=location.get("timezone") or "Europe/London",
                user_agent=self.user_agent,
                headless=self.headless,
            )
        else:
            browser = self._ensure_browser()
            context = browser.new_context(
                user_agent=self.user_agent,
                locale=location.get("locale") or "en-GB",
                timezone_id=location.get("timezone") or "Europe/London",
                viewport={"width": 1365, "height": 1800},
            )
            install_stealth_init(context)
        postcode = str(location.get("postcode") or "")
        if self.apply_location:
            page = context.new_page()
            home_url = f"https://www.amazon.{('co.uk' if marketplace_key == 'UK' else 'com' if marketplace_key == 'US' else 'de')}/"
            try:
                page.goto(home_url, wait_until="domcontentloaded", timeout=15000)
                self._location_notes[marketplace_key] = self.apply_delivery_location_func(
                    page,
                    marketplace_key,
                    postcode,
                )
            except Exception as exc:
                self._location_notes[marketplace_key] = f"{marketplace_key} {postcode} 未确认：{exc}" if postcode else ""
            finally:
                with contextlib.suppress(Exception):
                    page.close()
        else:
            self._location_notes[marketplace_key] = ""
        self._contexts[marketplace_key] = context
        return context

    def get_location_note(self, marketplace: str) -> str:
        marketplace_key = str(marketplace or "").strip().upper()
        if marketplace_key not in self._contexts:
            self.get_context(marketplace_key)
        return self._location_notes.get(marketplace_key, "")

    def close(self) -> None:
        for context in self._contexts.values():
            with contextlib.suppress(Exception):
                context.close()
        self._contexts.clear()
        if self._browser is not None:
            with contextlib.suppress(Exception):
                self._browser.close()
            self._browser = None
        if self._playwright_manager is not None:
            with contextlib.suppress(Exception):
                self._playwright_manager.stop()
            self._playwright_manager = None


def fetch_html_playwright(
    url: str,
    timeout: int,
    *,
    marketplace: str = "",
    attempt: int = 1,
    use_chrome: bool = False,
    browser_session: FrontendBrowserSession | None = None,
    user_agent: str,
    load_locations: LocationLoader,
    clean_location_text: TextCleaner,
    apply_delivery_location_func: Callable[..., str] | None = None,
    launch_chromium_func: Callable[..., object] | None = None,
) -> tuple[str, str, str]:
    if not importlib.util.find_spec("playwright"):
        return "", "Playwright 未安装", ""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - optional dependency guard
        return "", f"Playwright 不可用：{exc}", ""

    browser = None
    apply_func = apply_delivery_location_func or apply_delivery_location
    launch_func = launch_chromium_func or launch_chromium
    try:
        locations = load_locations()
        location = locations.get(str(marketplace or "").upper(), {})
        if browser_session is not None:
            context = browser_session.get_context(marketplace)
            page = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=max(timeout, 1) * 1000)
                with contextlib.suppress(PlaywrightTimeoutError, PlaywrightError):
                    page.wait_for_load_state("networkidle", timeout=4000 + max(attempt - 1, 0) * 2500)
                if attempt > 1:
                    page.wait_for_timeout(1000 * attempt)
                html = page.content()
                return html, "", browser_session.get_location_note(marketplace)
            finally:
                with contextlib.suppress(Exception):
                    page.close()
        with sync_playwright() as p:
            browser = launch_func(p, use_chrome)
            context = browser.new_context(
                user_agent=user_agent,
                locale=location.get("locale") or "en-GB",
                timezone_id=location.get("timezone") or "Europe/London",
                viewport={"width": 1365, "height": 1600},
            )
            install_stealth_init(context)
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=max(timeout, 1) * 1000)
            with contextlib.suppress(PlaywrightTimeoutError, PlaywrightError):
                page.wait_for_load_state("networkidle", timeout=4000 + max(attempt - 1, 0) * 2500)
            if attempt > 1:
                page.wait_for_timeout(1000 * attempt)
            location_note = apply_func(page, str(marketplace or "").upper(), location.get("postcode", ""))
            html = page.content()
            context.close()
            browser.close()
            return html, "", location_note
    except Exception as exc:
        method_name = "Chrome" if use_chrome else "Playwright"
        error = f"{method_name} 页面读取失败：{exc}"
    if browser:
        with contextlib.suppress(Exception):
            browser.close()
    return "", error, ""


def fetch_html(
    url: str,
    timeout: int,
    *,
    method: str = "auto",
    marketplace: str = "",
    attempt: int = 1,
    browser_session: FrontendBrowserSession | None = None,
    user_agent: str,
    load_locations: LocationLoader,
    clean_location_text: TextCleaner,
    apply_delivery_location_func: Callable[..., str] | None = None,
    launch_chromium_func: Callable[..., object] | None = None,
) -> tuple[str, str, str, str]:
    method = (method or "auto").lower()
    if method in {"chrome", "chrome-persistent"}:
        html, error, location_note = fetch_html_playwright(
            url,
            timeout,
            marketplace=marketplace,
            attempt=attempt,
            use_chrome=True,
            browser_session=browser_session,
            user_agent=user_agent,
            load_locations=load_locations,
            clean_location_text=clean_location_text,
            apply_delivery_location_func=apply_delivery_location_func,
            launch_chromium_func=launch_chromium_func,
        )
        if html or method in {"chrome", "chrome-persistent"}:
            return html, error, method, location_note
    if method in {"auto", "playwright"}:
        html, error, location_note = fetch_html_playwright(
            url,
            timeout,
            marketplace=marketplace,
            attempt=attempt,
            browser_session=browser_session,
            user_agent=user_agent,
            load_locations=load_locations,
            clean_location_text=clean_location_text,
            apply_delivery_location_func=apply_delivery_location_func,
            launch_chromium_func=launch_chromium_func,
        )
        if html or method == "playwright":
            return html, error, "playwright", location_note
    html, error = fetch_html_urllib(url, timeout, user_agent=user_agent)
    return html, error, "urllib", ""
