from __future__ import annotations

import pytest


def test_chrome_cdp_probe_rejects_missing_endpoint(monkeypatch) -> None:
    from scripts import probe_frontend_chrome_cdp as probe

    monkeypatch.setattr(probe, "_cdp_available", lambda endpoint: False)

    with pytest.raises(RuntimeError, match="Chrome CDP endpoint is not available"):
        probe.run_chrome_cdp_probe(
            endpoint="http://127.0.0.1:9222",
            marketplace="UK",
            asin="B0H73CXQ5J",
            attempts=20,
            sleep_seconds=0,
            timeout_seconds=1,
        )


def test_chrome_cdp_probe_main_writes_20_run_report(monkeypatch, tmp_path, capsys) -> None:
    import json
    import sys

    from scripts import probe_frontend_chrome_cdp as probe

    attempts_path = tmp_path / "attempts.json"
    report_path = tmp_path / "report.json"
    attempts = [
        {
            "attempt": index,
            "marketplace": "UK",
            "asin": "B0H73CXQ5J",
            "method": "chrome-cdp",
            "success": index != 16,
            "title": "Demo Adjustable Desk Lamp" if index != 16 else "",
            "price": "£17.89" if index != 16 else "",
            "location": "Aberdeen AB10 1" if index != 16 else "",
        }
        for index in range(1, 21)
    ]
    monkeypatch.setattr(
        probe,
        "run_chrome_cdp_probe",
        lambda **kwargs: {"generated_at": "2026-06-16T23:30:00", "attempts": attempts},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "probe_frontend_chrome_cdp.py",
            "--marketplace",
            "UK",
            "--asin",
            "B0H73CXQ5J",
            "--attempts-output",
            str(attempts_path),
            "--report-output",
            str(report_path),
        ],
    )

    code = probe.main()

    assert code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["total_attempts"] == 20
    assert report["success_count"] == 19
    assert report["passed"] is True
    assert "[chrome-cdp-probe] 19/20 success" in capsys.readouterr().out


def test_chrome_cdp_probe_recovers_readable_dom_after_navigation_timeout(monkeypatch) -> None:
    from scripts import probe_frontend_chrome_cdp as probe

    class FakeTimeoutError(Exception):
        pass

    class FakePage:
        url = "https://www.amazon.co.uk/dp/B0H73CXQ5J?th=1"

        def goto(self, *args, **kwargs):
            raise FakeTimeoutError("Timed out waiting for domcontentloaded")

        def wait_for_load_state(self, *args, **kwargs):
            return None

        def wait_for_timeout(self, *args, **kwargs):
            return None

        def evaluate(self, script):
            if script == "() => window.stop()":
                return None
            return {
                "title": "Demo Adjustable Desk Lamp",
                "price": "£17.89",
                "rating": "4.2 out of 5 stars",
                "reviews": "(38)",
                "location": "Aberdeen AB10 1",
                "buy_box": "识别到购买按钮",
                "captcha_or_block": False,
                "url": self.url,
            }

    class FakeContext:
        pages = [FakePage()]

    class FakeBrowser:
        contexts = [FakeContext()]

        def close(self):
            return None

    class FakeChromium:
        def connect_over_cdp(self, endpoint):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakePlaywrightManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(probe, "_cdp_available", lambda endpoint: True)
    monkeypatch.setattr(
        probe,
        "sync_playwright",
        None,
        raising=False,
    )

    original_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "playwright.sync_api":
            class Module:
                TimeoutError = FakeTimeoutError

                @staticmethod
                def sync_playwright():
                    return FakePlaywrightManager()

            return Module
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    payload = probe.run_chrome_cdp_probe(
        endpoint="http://127.0.0.1:9222",
        marketplace="UK",
        asin="B0H73CXQ5J",
        attempts=1,
        sleep_seconds=0,
        timeout_seconds=1,
    )

    row = payload["attempts"][0]
    assert row["success"] is True
    assert row["price"] == "£17.89"
    assert "Timed out waiting for domcontentloaded" in row["navigation_warning"]


def test_chrome_cdp_probe_clicks_continue_shopping_gate(monkeypatch) -> None:
    from scripts import probe_frontend_chrome_cdp as probe

    class FakeTimeoutError(Exception):
        pass

    class FakePage:
        url = "https://www.amazon.co.uk/dp/B0H73CXQ5J?th=1"

        def __init__(self):
            self.dismissed = False

        def goto(self, *args, **kwargs):
            return None

        def wait_for_load_state(self, *args, **kwargs):
            return None

        def wait_for_timeout(self, *args, **kwargs):
            return None

        def evaluate(self, script):
            if script == probe.CLICK_CONTINUE_SHOPPING_JS:
                self.dismissed = True
                return True
            if not self.dismissed:
                return {
                    "title": "Amazon.co.uk",
                    "price": "",
                    "rating": "",
                    "reviews": "",
                    "location": "",
                    "buy_box": "",
                    "captcha_or_block": False,
                    "continue_shopping": True,
                    "url": self.url,
                }
            return {
                "title": "Demo Adjustable Desk Lamp",
                "price": "£17.89",
                "rating": "4.2 out of 5 stars",
                "reviews": "(38)",
                "location": "Aberdeen AB10 1",
                "buy_box": "识别到购买按钮",
                "captcha_or_block": False,
                "continue_shopping": False,
                "url": self.url,
            }

    class FakeContext:
        pages = [FakePage()]

    class FakeBrowser:
        contexts = [FakeContext()]

        def close(self):
            return None

    class FakeChromium:
        def connect_over_cdp(self, endpoint):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakePlaywrightManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(probe, "_cdp_available", lambda endpoint: True)
    monkeypatch.setattr(probe, "_prepare_product_page", lambda *args, **kwargs: "")
    original_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "playwright.sync_api":
            class Module:
                TimeoutError = FakeTimeoutError

                @staticmethod
                def sync_playwright():
                    return FakePlaywrightManager()

            return Module
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    payload = probe.run_chrome_cdp_probe(
        endpoint="http://127.0.0.1:9222",
        marketplace="UK",
        asin="B0H73CXQ5J",
        attempts=1,
        sleep_seconds=0,
        timeout_seconds=1,
    )

    row = payload["attempts"][0]
    assert row["success"] is True
    assert row["continue_shopping_page"] is True
    assert row["continue_shopping_dismissed"] is True
    assert row["price"] == "£17.89"


def test_chrome_cdp_probe_uses_verified_location_setup_note(monkeypatch) -> None:
    from scripts import probe_frontend_chrome_cdp as probe

    class FakeTimeoutError(Exception):
        pass

    class FakePage:
        url = "https://www.amazon.co.uk/dp/B0H73CXQ5J?th=1"

        def goto(self, *args, **kwargs):
            return None

        def wait_for_load_state(self, *args, **kwargs):
            return None

        def wait_for_timeout(self, *args, **kwargs):
            return None

        def evaluate(self, script):
            if script == probe.CLICK_CONTINUE_SHOPPING_JS:
                return False
            if script == probe.DISMISS_COOKIE_BANNER_JS:
                return False
            return {
                "title": "Demo Adjustable Desk Lamp",
                "price": "£17.89",
                "rating": "4.2 out of 5 stars",
                "reviews": "(38)",
                "location": "Thailand",
                "buy_box": "识别到购买按钮",
                "captcha_or_block": False,
                "continue_shopping": False,
                "url": self.url,
            }

    class FakeContext:
        pages = [FakePage()]

    class FakeBrowser:
        contexts = [FakeContext()]

        def close(self):
            return None

    class FakeChromium:
        def connect_over_cdp(self, endpoint):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakePlaywrightManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(probe, "_cdp_available", lambda endpoint: True)
    monkeypatch.setattr(probe, "_apply_delivery_location", lambda page, marketplace, timeout_error: "UK SW1A 1AA 已设置")
    original_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "playwright.sync_api":
            class Module:
                TimeoutError = FakeTimeoutError

                @staticmethod
                def sync_playwright():
                    return FakePlaywrightManager()

            return Module
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    payload = probe.run_chrome_cdp_probe(
        endpoint="http://127.0.0.1:9222",
        marketplace="UK",
        asin="B0H73CXQ5J",
        attempts=1,
        sleep_seconds=0,
        timeout_seconds=1,
    )

    row = payload["attempts"][0]
    assert row["success"] is True
    assert row["visible_location"] == "Thailand"
    assert row["location"] == "UK SW1A 1AA 已设置"


def test_verified_location_setup_accepts_shortened_uk_postcode() -> None:
    from scripts import probe_frontend_chrome_cdp as probe

    assert probe._verified_location_setup("London SW1A 1\u200c", "UK") is True
    assert probe._verified_location_setup("Thailand", "UK") is False


def test_apply_frontend_payload_replaces_invalid_setup_note_with_visible_location() -> None:
    from scripts import probe_frontend_chrome_cdp as probe

    row = {"marketplace": "US", "location_setup_note": "Update location"}

    probe._apply_frontend_payload(
        row,
        {
            "title": "US product",
            "price": "$16.04",
            "rating": "4.1 out of 5 stars",
            "reviews": "(53)",
            "location": "New York 10001\u200c",
            "buy_box": "识别到购买按钮",
            "captcha_or_block": False,
            "continue_shopping": False,
            "url": "https://www.amazon.com/dp/B0TEST1234",
        },
    )

    assert row["location"] == "New York 10001\u200c"
    assert "location_setup_note" not in row
    assert row["success"] is True


def test_chrome_cdp_probe_retries_update_location_marker(monkeypatch) -> None:
    from scripts import probe_frontend_chrome_cdp as probe

    class FakeTimeoutError(Exception):
        pass

    class FakePage:
        url = "https://www.amazon.com/dp/B0TEST1234"

        def __init__(self):
            self.location_fixed = False

        def goto(self, *args, **kwargs):
            return None

        def wait_for_load_state(self, *args, **kwargs):
            return None

        def wait_for_timeout(self, *args, **kwargs):
            return None

        def evaluate(self, script):
            if script == probe.CLICK_CONTINUE_SHOPPING_JS:
                return False
            if script == probe.DISMISS_COOKIE_BANNER_JS:
                return False
            return {
                "title": "US product",
                "price": "$16.79",
                "rating": "3.9 out of 5 stars",
                "reviews": "(52)",
                "location": "US 10001 已设置" if self.location_fixed else "Update location",
                "buy_box": "识别到购买按钮",
                "captcha_or_block": False,
                "continue_shopping": False,
                "url": self.url,
            }

    page = FakePage()

    class FakeContext:
        pages = [page]

    class FakeBrowser:
        contexts = [FakeContext()]

        def close(self):
            return None

    class FakeChromium:
        def connect_over_cdp(self, endpoint):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakePlaywrightManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(probe, "_cdp_available", lambda endpoint: True)

    def fake_apply_delivery_location(*args, **kwargs):
        page.location_fixed = True
        return "US 10001 已设置"

    monkeypatch.setattr(probe, "_apply_delivery_location", fake_apply_delivery_location)
    original_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "playwright.sync_api":
            class Module:
                TimeoutError = FakeTimeoutError

                @staticmethod
                def sync_playwright():
                    return FakePlaywrightManager()

            return Module
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    payload = probe.run_chrome_cdp_probe(
        endpoint="http://127.0.0.1:9222",
        marketplace="US",
        asin="B0TEST1234",
        attempts=1,
        sleep_seconds=0,
        timeout_seconds=1,
    )

    row = payload["attempts"][0]
    assert row["success"] is True
    assert row["location"] == "US 10001 已设置"


def test_chrome_cdp_probe_warms_location_before_counting_attempts(monkeypatch) -> None:
    from scripts import probe_frontend_chrome_cdp as probe

    class FakeTimeoutError(Exception):
        pass

    class FakePage:
        url = "https://www.amazon.com/dp/B0TEST1234"

        def __init__(self):
            self.setup_calls = 0

        def goto(self, *args, **kwargs):
            return None

        def wait_for_load_state(self, *args, **kwargs):
            return None

        def wait_for_timeout(self, *args, **kwargs):
            return None

        def reload(self, *args, **kwargs):
            return None

        def evaluate(self, script):
            if script == probe.CLICK_CONTINUE_SHOPPING_JS:
                return False
            if script == probe.DISMISS_COOKIE_BANNER_JS:
                return False
            location = "US 10001 已设置" if self.setup_calls >= 2 else "Update location"
            return {
                "title": "US product",
                "price": "$16.79",
                "rating": "3.9 out of 5 stars",
                "reviews": "(52)",
                "location": location,
                "buy_box": "识别到购买按钮",
                "captcha_or_block": False,
                "continue_shopping": False,
                "url": self.url,
            }

    page = FakePage()

    class FakeContext:
        pages = [page]

    class FakeBrowser:
        contexts = [FakeContext()]

        def close(self):
            return None

    class FakeChromium:
        def connect_over_cdp(self, endpoint):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakePlaywrightManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(probe, "_cdp_available", lambda endpoint: True)

    def fake_apply_delivery_location(*args, **kwargs):
        page.setup_calls += 1
        return "US 10001 已设置" if page.setup_calls >= 2 else "Update location"

    monkeypatch.setattr(probe, "_apply_delivery_location", fake_apply_delivery_location)
    original_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "playwright.sync_api":
            class Module:
                TimeoutError = FakeTimeoutError

                @staticmethod
                def sync_playwright():
                    return FakePlaywrightManager()

            return Module
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    payload = probe.run_chrome_cdp_probe(
        endpoint="http://127.0.0.1:9222",
        marketplace="US",
        asin="B0TEST1234",
        attempts=1,
        sleep_seconds=0,
        timeout_seconds=1,
    )

    row = payload["attempts"][0]
    assert page.setup_calls == 2
    assert row["success"] is True
    assert row["location"] == "US 10001 已设置"


def test_read_frontend_payload_retries_empty_product_fields() -> None:
    from scripts import probe_frontend_chrome_cdp as probe

    class FakeTimeoutError(Exception):
        pass

    class FakePage:
        def __init__(self):
            self.calls = 0

        def evaluate(self, script):
            self.calls += 1
            if self.calls == 1:
                return {"title": "Amazon.co.uk", "price": "", "location": "London SW1A 1"}
            return {"title": "Tea organizer", "price": "£17.89", "location": "London SW1A 1"}

        def wait_for_timeout(self, *args, **kwargs):
            return None

        def wait_for_load_state(self, *args, **kwargs):
            return None

    page = FakePage()

    payload = probe._read_frontend_payload(page, FakeTimeoutError)

    assert payload["price"] == "£17.89"
    assert page.calls == 2
