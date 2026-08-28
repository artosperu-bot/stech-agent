from __future__ import annotations

from pathlib import Path
import os
import re
import time
from typing import Callable, Any

from stech_agent.stech.selectors import locate

HOME_URL = "https://www.s-tech.com.pe/admin/home"
ITEMS_URL = "https://www.s-tech.com.pe/admin/items"


def default_app_root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "STECH_PRODUCT_AGENT"


def stech_profile_dir(app_root: str | Path | None = None) -> Path:
    root = Path(app_root) if app_root is not None else default_app_root()
    path = root / "profiles" / "stech_chrome"
    path.mkdir(parents=True, exist_ok=True)
    return path


class StechSession:
    def __init__(
        self,
        *,
        app_root: str | Path | None = None,
        log: Callable[[str], None] | None = None,
        stop_event=None,
        slow_mo: int = 500,
        login_timeout_seconds: int = 7200,
        playwright_starter: Callable[[], Any] | None = None,
        auto_navigate: bool = True,
    ):
        self.app_root = Path(app_root) if app_root is not None else default_app_root()
        self.log = log or (lambda _msg: None)
        self.stop_event = stop_event
        self.slow_mo = slow_mo
        self.login_timeout_seconds = login_timeout_seconds
        self.auto_navigate = auto_navigate
        self._playwright_starter = playwright_starter
        self._pw = None
        self.context = None
        self.page = None
        self._owns_context = False
        self.screenshot_dir = self.app_root / "logs"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def _start_playwright(self):
        if self._playwright_starter is not None:
            return self._playwright_starter()
        from playwright.sync_api import sync_playwright
        return sync_playwright().start()

    def start(self):
        if self.context is not None:
            return self
        self.log("[WEB] Abriendo Chrome para S-TECH...")
        self._pw = self._start_playwright()
        kwargs = {
            "user_data_dir": str(stech_profile_dir(self.app_root)),
            "headless": False,
            "slow_mo": self.slow_mo,
            "viewport": {"width": 1440, "height": 900},
        }
        try:
            self.context = self._pw.chromium.launch_persistent_context(channel="chrome", **kwargs)
        except TypeError:
            self.context = self._pw.chromium.launch_persistent_context(**kwargs)
        except Exception:
            self.context = self._pw.chromium.launch_persistent_context(**kwargs)
        self._owns_context = True
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.set_default_timeout(25_000)
        if self.auto_navigate:
            self.ensure_products_page()
        return self

    def _stop_check(self):
        if self.stop_event is not None and self.stop_event.is_set():
            raise RuntimeError("Proceso detenido por el usuario")

    def _login_visible(self) -> bool:
        try:
            return self.page.get_by_role("textbox", name="Correo o Usuario").is_visible(timeout=700)
        except Exception:
            return False

    def _wait_login(self):
        deadline = time.monotonic() + self.login_timeout_seconds
        last_notice = 0.0
        while time.monotonic() < deadline:
            self._stop_check()
            if self.page.is_closed():
                raise RuntimeError("Se cerró Chrome de S-TECH")
            url = (self.page.url or "").lower()
            if "/admin/" in url and "/login" not in url and not self._login_visible():
                self.log("[WEB] Login S-TECH detectado.")
                return
            now = time.monotonic()
            if now - last_notice >= 60:
                self.log("[WEB] Esperando que completes el login de S-TECH...")
                last_notice = now
            self.page.wait_for_timeout(1000)
        raise RuntimeError("Se agotó el tiempo de login S-TECH")

    def ensure_products_page(self):
        if self.page is None:
            raise RuntimeError("Sesión S-TECH no iniciada")
        self.page.goto(ITEMS_URL, wait_until="domcontentloaded", timeout=90_000)
        self.page.wait_for_timeout(1000)
        if "/login" in (self.page.url or "").lower() or self._login_visible():
            self.log("[WEB] S-TECH requiere login manual; esperaré.")
            self._wait_login()
            self.page.goto(ITEMS_URL, wait_until="domcontentloaded", timeout=90_000)
        locate(self.page, "sku_filter").wait_for(state="visible", timeout=40_000)
        self.log("[WEB] Lista de Items lista.")
        return self.page

    def recover(self):
        if self.page is None or self.page.is_closed():
            return
        try:
            close = locate(self.page, "close")
            if close.count() and close.first.is_visible(timeout=600):
                close.first.click()
                self.page.wait_for_timeout(500)
        except Exception:
            pass
        try:
            locate(self.page, "sku_filter").wait_for(state="visible", timeout=1200)
            return
        except Exception:
            self.ensure_products_page()

    def screenshot(self, label: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", label)[:90]
        path = self.screenshot_dir / f"STECH_{safe}_{time.strftime('%Y%m%d_%H%M%S')}.png"
        if self.page is not None:
            try:
                self.page.screenshot(path=str(path), full_page=True)
            except Exception:
                pass
        return path

    def close(self):
        if self._owns_context and self.context is not None:
            try:
                self.context.close()
            except Exception:
                pass
        self.context = None
        self.page = None
        self._owns_context = False
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
        self._pw = None
