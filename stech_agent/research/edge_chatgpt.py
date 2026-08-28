from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import json
import os
import re
import socket
import subprocess
import time
import urllib.request

from stech_agent.prompts.registry import PromptRegistry
from stech_agent.seo.v72 import build_research_prompt, extract_json_object, validate_seo_payload


CHATGPT_URL = "https://chatgpt.com/"


class ChatGPTTransientError(RuntimeError):
    """Global/account-side temporary condition: wait before retrying."""


class ChatGPTConversationLimitError(RuntimeError):
    """The current conversation/UI must be replaced with a fresh chat."""


@dataclass(frozen=True, slots=True)
class ResearchSeoResult:
    payload: dict[str, Any]
    raw_text: str
    raw_path: Path
    prompt_id: str
    prompt_version: str
    prompt_hash: str
    provider_id: str = "edge-chatgpt"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().casefold()


def composer_prompt_text(text: str) -> str:
    """Flatten newlines because Selenium send_keys treats them as ENTER."""
    return re.sub(r"[\r\n\t]+", " ", text or "").strip()


def prompt_delivery_matches(expected: str, actual: str) -> bool:
    exp = _norm(expected)
    got = _norm(actual)
    if not exp or not got:
        return False
    if len(exp) <= 160:
        return exp == got
    head = exp[:120]
    tail = exp[-120:]
    return len(got) >= int(len(exp) * 0.80) and head in got and tail in got


def looks_conversation_limit(text: str) -> bool:
    low = _norm(text)
    patterns = [
        "límite de longitud de esta conversación",
        "limite de longitud de esta conversacion",
        "esta conversación ha alcanzado",
        "esta conversacion ha alcanzado",
        "conversation has reached its limit",
        "maximum length for this conversation",
        "start a new chat",
        "inicia un nuevo chat",
    ]
    return any(pattern in low for pattern in patterns)


def looks_transient(text: str) -> bool:
    low = _norm(text)
    patterns = [
        "you've reached your usage limit",
        "you have reached your usage limit",
        "usage limit",
        "rate limit",
        "try again later",
        "something went wrong",
        "error in message stream",
        "has alcanzado tu límite de uso",
        "has alcanzado tu limite de uso",
        "límite de uso",
        "limite de uso",
        "inténtalo de nuevo más tarde",
        "intentalo de nuevo mas tarde",
        "demasiadas solicitudes",
        "too many requests",
        "temporarily unavailable",
        "temporalmente no disponible",
    ]
    return any(pattern in low for pattern in patterns) and not looks_conversation_limit(text)


def looks_auth_gate(text: str) -> bool:
    low = _norm(text)
    patterns = [
        "para continuar, inicia sesión",
        "para continuar inicia sesión",
        "inicia sesión para continuar",
        "inicia sesion para continuar",
        "crea una cuenta para continuar",
        "log in to continue",
        "login to continue",
        "sign in to continue",
        "create an account to continue",
    ]
    return any(pattern in low for pattern in patterns)


def _top_level_json_objects(text: str) -> list[str]:
    out: list[str] = []
    start = None
    depth = 0
    in_string = False
    escape = False
    for idx, ch in enumerate(text or ""):
        if start is None:
            if ch == "{":
                start = idx
                depth = 1
                in_string = False
                escape = False
            continue
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                out.append((text or "")[start:idx + 1])
                start = None
    return out


def choose_body_json_response(body_text: str, prompt_text: str) -> str:
    prompt_objects = {_norm(obj) for obj in _top_level_json_objects(prompt_text)}
    for candidate in reversed(_top_level_json_objects(body_text)):
        if _norm(candidate) in prompt_objects:
            continue
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return candidate
    return ""


SEO_RESPONSE_MARKERS = [
    '"marca"',
    '"modelo"',
    '"categoria"',
    '"titulo_seo"',
    '"descripcion_seo"',
    '"keywords_seo"',
    '"faqs"',
    '"fuentes_tecnicas"',
    '"observacion_seo"',
]


def looks_like_complete_seo_response(text: str) -> bool:
    raw = (text or "").strip()
    if not raw or "{" not in raw or "}" not in raw:
        return False
    low = raw.casefold()
    marker_hits = sum(1 for marker in SEO_RESPONSE_MARKERS if marker.casefold() in low)
    if marker_hits < 7:
        return False
    obs = low.rfind('"observacion_seo"')
    return obs >= 0 and raw.find("}", obs) >= 0


def _seo_objectish_candidates(text: str) -> list[str]:
    raw = text or ""
    low = raw.casefold()
    out: list[str] = []
    search_end = len(raw)
    marker = '"observacion_seo"'
    while True:
        obs = low.rfind(marker, 0, search_end)
        if obs < 0:
            break
        marca = low.rfind('"marca"', 0, obs)
        if marca < 0:
            search_end = obs
            continue
        start = raw.rfind("{", 0, marca + 1)
        end = raw.find("}", obs)
        if start >= 0 and end >= 0:
            candidate = raw[start:end + 1].strip()
            if looks_like_complete_seo_response(candidate):
                out.append(candidate)
        search_end = obs
    return out


def choose_body_response_candidate(body_text: str, prompt_text: str) -> str:
    strict = choose_body_json_response(body_text, prompt_text)
    if strict:
        return strict
    prompt_norm = _norm(prompt_text)
    for candidate in _seo_objectish_candidates(body_text):
        cand_norm = _norm(candidate)
        if cand_norm and cand_norm not in prompt_norm:
            return candidate
    return ""


def choose_response_text(
    texts: list[str],
    prompt_text: str,
    baseline_norms: set[str] | None = None,
) -> str:
    prompt_norm = _norm(prompt_text)
    baseline_norms = baseline_norms or set()
    for text in reversed(texts):
        if not text or len(text.strip()) < 8:
            continue
        current = text.strip()
        low = _norm(current)
        if low in baseline_norms or low == prompt_norm:
            continue
        if "producto a investigar:" in low and "reglas finales:" in low:
            continue
        if "objetivo:" in low and "respuesta:" in low and "devuelve solo json" in low:
            continue
        if looks_conversation_limit(current) or looks_transient(current) or looks_auth_gate(current):
            return current
        try:
            extract_json_object(current)
            return current
        except Exception:
            if looks_like_complete_seo_response(current):
                return current
    return ""


def app_base_dir() -> Path:
    base = Path(os.getenv("LOCALAPPDATA") or Path.home()) / "STECH_PRODUCT_AGENT"
    base.mkdir(parents=True, exist_ok=True)
    return base


def real_edge_profile_dir() -> Path:
    local = Path(os.getenv("LOCALAPPDATA") or Path.home())
    legacy = local / "SEO_PRODUCTOS_STECH" / "profiles" / "chatgpt_edge_real"
    if legacy.exists():
        return legacy
    path = app_base_dir() / "profiles" / "research_edge_real"
    path.mkdir(parents=True, exist_ok=True)
    return path


def debug_endpoint_url(port: int) -> str:
    return f"http://127.0.0.1:{int(port)}/json/version"


def find_edge_executable() -> Path:
    candidates = [
        Path(os.getenv("PROGRAMFILES(X86)") or r"C:\Program Files (x86)") / "Microsoft/Edge/Application/msedge.exe",
        Path(os.getenv("PROGRAMFILES") or r"C:\Program Files") / "Microsoft/Edge/Application/msedge.exe",
        Path(os.getenv("LOCALAPPDATA") or "") / "Microsoft/Edge/Application/msedge.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise RuntimeError("No encontré msedge.exe. Instala Microsoft Edge o revisa su ruta.")


def build_edge_debug_command(edge_exe: Path, profile_dir: Path, port: int) -> list[str]:
    return [
        str(edge_exe),
        f"--remote-debugging-port={int(port)}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        CHATGPT_URL,
    ]


def _debug_endpoint_info(port: int, timeout: float = 0.7) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(debug_endpoint_url(port), timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception:
        return {}


def _is_edge_debug_endpoint(port: int) -> bool:
    info = _debug_endpoint_info(port)
    browser = str(info.get("Browser") or info.get("browser") or "").casefold()
    return bool(info) and ("edg/" in browser or "edge" in browser)


def _port_free(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", int(port)))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def find_or_choose_debug_port(preferred: int = 9222) -> tuple[int, bool]:
    env = os.getenv("SEO_CHATGPT_DEBUG_PORT", "").strip()
    if env.isdigit():
        port = int(env)
        return port, _is_edge_debug_endpoint(port)
    ports = list(range(preferred, preferred + 11))
    for port in ports:
        if _is_edge_debug_endpoint(port):
            return port, True
    for port in ports:
        if _port_free(port):
            return port, False
    raise RuntimeError("No encontré un puerto libre entre 9222 y 9232 para Edge/ChatGPT.")


class EdgeChatGPTWorker:
    """V7.2-compatible ChatGPT worker attached to normal Microsoft Edge via CDP."""

    def __init__(
        self,
        raw_dir: str | Path,
        log_callback: Callable[[str], None] | None = None,
        stop_event=None,
        slow_mo: int = 650,
        login_timeout_seconds: int = 7200,
        response_timeout_seconds: int = 720,
    ):
        self.raw_dir = Path(raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.diagnostics_dir = self.raw_dir / "diagnosticos"
        self.diagnostics_dir.mkdir(parents=True, exist_ok=True)
        self.log = log_callback or (lambda _msg: None)
        self.stop_event = stop_event
        self.slow_mo = slow_mo
        self.login_timeout_seconds = login_timeout_seconds
        self.response_timeout_seconds = response_timeout_seconds
        self.driver = None
        self.edge_process = None
        self.debug_port = None
        self.page = None

    @staticmethod
    def _selenium():
        try:
            from selenium import webdriver
            from selenium.webdriver.common.by import By
            from selenium.webdriver.common.keys import Keys
            from selenium.webdriver.edge.options import Options
            return webdriver, By, Keys, Options
        except Exception as exc:
            raise RuntimeError("Falta Selenium. Ejecuta pip install -e '.[dev]' nuevamente.") from exc

    def is_alive(self) -> bool:
        if not self.driver:
            return False
        try:
            _ = self.driver.current_url
            return True
        except Exception:
            return False

    def _check_stop(self) -> None:
        if self.stop_event is not None and self.stop_event.is_set():
            raise RuntimeError("Proceso detenido por el usuario")

    def _sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self._check_stop()
            time.sleep(min(0.2, max(0.01, deadline - time.monotonic())))

    def _wait_debug_endpoint(self, port: int, seconds: int = 90) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self._check_stop()
            if _is_edge_debug_endpoint(port):
                return True
            time.sleep(0.5)
        return False

    def _launch_real_edge(self, port: int) -> None:
        edge = find_edge_executable()
        profile = real_edge_profile_dir()
        cmd = build_edge_debug_command(edge, profile, port)
        self.log("[RESEARCH] Abriendo Edge normal con perfil persistente de ChatGPT...")
        self.log(f"[RESEARCH] Perfil Edge: {profile}")
        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        self.edge_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )

    def start(self) -> None:
        if self.is_alive():
            return
        port, existing = find_or_choose_debug_port()
        self.debug_port = port
        if existing:
            self.log(f"[RESEARCH] Reutilizando Edge preparado en puerto {port}.")
        else:
            self._launch_real_edge(port)
            if not self._wait_debug_endpoint(port, 90):
                raise RuntimeError(
                    "Edge abrió pero no habilitó la conexión local. Cierra todas las ventanas de Edge y vuelve a intentar."
                )
        webdriver, _By, _Keys, Options = self._selenium()
        last_exc = None
        for attempt in range(3):
            try:
                options = Options()
                options.debugger_address = f"127.0.0.1:{port}"
                self.log(f"[RESEARCH] Conectando Selenium a Edge 127.0.0.1:{port}...")
                self.driver = webdriver.Edge(options=options)
                break
            except Exception as exc:
                last_exc = exc
                self.log(f"[RESEARCH] Conexión Edge {attempt + 1}/3 falló: {type(exc).__name__}: {exc}")
                time.sleep(2)
        if not self.driver:
            raise RuntimeError(f"No pude conectar Selenium al Edge real: {last_exc}")
        self.page = self.driver
        try:
            self.driver.set_page_load_timeout(90)
        except Exception:
            pass
        self._select_or_open_chatgpt_tab()
        self._wait_ready()
        self.log("[RESEARCH] ChatGPT listo en Edge. La sesión queda guardada en el perfil.")

    def close(self) -> None:
        # This is the user's Edge. Stop WebDriver service without closing the browser.
        if self.driver:
            try:
                service = getattr(self.driver, "service", None)
                if service:
                    service.stop()
            except Exception:
                pass
        self.driver = None
        self.page = None

    def _select_or_open_chatgpt_tab(self) -> None:
        assert self.driver is not None
        for handle in list(self.driver.window_handles):
            try:
                self.driver.switch_to.window(handle)
                if "chatgpt.com" in (self.driver.current_url or "").casefold():
                    return
            except Exception:
                continue
        self.driver.switch_to.new_window("tab")
        self.driver.get(CHATGPT_URL)

    def _prompt_element(self):
        assert self.driver is not None
        _webdriver, By, _Keys, _Options = self._selenium()
        for selector in ["#prompt-textarea", "textarea", "[contenteditable='true']"]:
            try:
                for element in reversed(self.driver.find_elements(By.CSS_SELECTOR, selector)):
                    if element.is_displayed() and element.is_enabled():
                        return element
            except Exception:
                continue
        return None

    def _body_text(self) -> str:
        if not self.driver:
            return ""
        _webdriver, By, _Keys, _Options = self._selenium()
        try:
            return self.driver.find_element(By.TAG_NAME, "body").text or ""
        except Exception:
            return ""

    def _logged_out_header_visible(self) -> bool:
        if not self.driver:
            return True
        _webdriver, By, _Keys, _Options = self._selenium()
        labels = ["Iniciar sesión", "Iniciar sesion", "Crear cuenta", "Log in", "Sign in", "Sign up"]
        for label in labels:
            xpath = (
                "//*[self::button or self::a or @role='button' or @role='link']"
                f"[normalize-space(.)={json.dumps(label)}]"
            )
            try:
                if any(element.is_displayed() for element in self.driver.find_elements(By.XPATH, xpath)):
                    return True
            except Exception:
                continue
        return False

    def _dismiss_soft_overlays(self) -> bool:
        if not self.driver:
            return False
        _webdriver, By, _Keys, _Options = self._selenium()
        try:
            dialogs = [d for d in self.driver.find_elements(By.CSS_SELECTOR, "[role='dialog']") if d.is_displayed()]
        except Exception:
            dialogs = []
        if not dialogs:
            return False
        allowed = {"cerrar", "close", "ahora no", "not now", "no gracias", "no thanks", "entendido", "got it", "aceptar"}
        try:
            for button in dialogs[-1].find_elements(By.CSS_SELECTOR, "button,[role='button']"):
                label = _norm(button.text or button.get_attribute("aria-label") or "")
                if label in allowed and button.is_displayed():
                    button.click()
                    self._sleep(0.5)
                    return True
        except Exception:
            pass
        return False

    def _wait_ready(self) -> None:
        assert self.driver is not None
        deadline = time.monotonic() + self.login_timeout_seconds
        auth_notice = False
        last_notice = 0.0
        while time.monotonic() < deadline:
            self._check_stop()
            if not self.is_alive():
                raise RuntimeError("Se cerró Edge de ChatGPT")
            self._dismiss_soft_overlays()
            prompt = self._prompt_element()
            logged_out = self._logged_out_header_visible()
            if prompt is not None and prompt.is_displayed() and not logged_out:
                self._sleep(1.5)
                return
            if logged_out and not auth_notice:
                self.log("[RESEARCH] Inicia sesión manualmente en ChatGPT. No enviaré prompts sin login.")
                auth_notice = True
            now = time.monotonic()
            if now - last_notice >= 30:
                self.log("[RESEARCH] Esperando login de ChatGPT; el SKU queda pendiente y no se pierde.")
                last_notice = now
            self._sleep(1.0)
        raise RuntimeError("Se agotó el tiempo de espera de ChatGPT")

    def _open_new_chat(self) -> None:
        assert self.driver is not None
        self.driver.get(CHATGPT_URL)
        self._wait_ready()
        self._sleep(1.0)

    def _response_texts(self) -> list[str]:
        if not self.driver:
            return []
        _webdriver, By, _Keys, _Options = self._selenium()
        selectors = [
            "[data-message-author-role='assistant']",
            "main article [class*='markdown']",
            "main article [class*='prose']",
            "main article",
        ]
        out: list[str] = []
        seen: set[str] = set()
        for selector in selectors:
            try:
                for element in self.driver.find_elements(By.CSS_SELECTOR, selector)[-10:]:
                    if not element.is_displayed():
                        continue
                    text = (element.text or "").strip()
                    key = _norm(text)
                    if text and key not in seen:
                        seen.add(key)
                        out.append(text)
            except Exception:
                continue
        return out

    def _stop_button_visible(self) -> bool:
        if not self.driver:
            return False
        _webdriver, By, _Keys, _Options = self._selenium()
        for selector in [
            "button[data-testid='stop-button']",
            "button[aria-label*='Stop' i]",
            "button[aria-label*='Detener' i]",
        ]:
            try:
                if any(element.is_displayed() for element in self.driver.find_elements(By.CSS_SELECTOR, selector)):
                    return True
            except Exception:
                pass
        return False

    def _save_diagnostic(self, reason: str) -> str:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", reason)[:50]
        png = self.diagnostics_dir / f"{stamp}_{safe}.png"
        txt = self.diagnostics_dir / f"{stamp}_{safe}.txt"
        if self.driver:
            try:
                self.driver.save_screenshot(str(png))
            except Exception:
                pass
        try:
            txt.write_text(self._body_text(), encoding="utf-8")
        except Exception:
            pass
        return str(png)

    @staticmethod
    def _composer_value(element) -> str:
        try:
            tag = (element.tag_name or "").casefold()
        except Exception:
            tag = ""
        if tag in {"textarea", "input"}:
            try:
                return element.get_attribute("value") or ""
            except Exception:
                return ""
        try:
            return element.get_attribute("innerText") or element.text or ""
        except Exception:
            return ""

    def _last_user_message_text(self) -> str:
        if not self.driver:
            return ""
        _webdriver, By, _Keys, _Options = self._selenium()
        for selector in ["[data-message-author-role='user']", "main article[data-testid^='conversation-turn']"]:
            try:
                elements = [e for e in self.driver.find_elements(By.CSS_SELECTOR, selector) if e.is_displayed()]
                if not elements:
                    continue
                if selector.startswith("main article"):
                    for element in reversed(elements):
                        text = (element.text or "").strip()
                        if text:
                            return text
                return (elements[-1].text or "").strip()
            except Exception:
                continue
        return ""

    def _fill_prompt(self, element, prompt_text: str) -> str:
        _webdriver, _By, Keys, _Options = self._selenium()
        safe_text = composer_prompt_text(prompt_text)
        element.click()
        self._sleep(0.2)
        try:
            element.send_keys(Keys.CONTROL, "a")
            element.send_keys(Keys.BACKSPACE)
        except Exception:
            pass
        element.send_keys(safe_text)
        self._sleep(0.3)
        written = self._composer_value(element)
        if not prompt_delivery_matches(safe_text, written):
            raise RuntimeError(
                "ChatGPT no recibió el prompt completo en el compositor "
                f"({len(_norm(written))}/{len(_norm(safe_text))} caracteres normalizados)."
            )
        return safe_text

    def _send_prompt(self, prompt_text: str) -> str:
        assert self.driver is not None
        _webdriver, By, Keys, _Options = self._selenium()
        self._wait_ready()
        self._dismiss_soft_overlays()
        baseline_norms = {_norm(text) for text in self._response_texts() if text.strip()}
        prompt = self._prompt_element()
        if prompt is None:
            raise RuntimeError("No encuentro el cuadro para escribir en ChatGPT")
        typed_prompt = self._fill_prompt(prompt, prompt_text)
        self.log(f"[RESEARCH] Prompt completo cargado ({len(typed_prompt)} caracteres).")
        self._sleep(0.7)
        sent = False
        for selector in [
            "button[data-testid='send-button']",
            "button[aria-label*='Send' i]",
            "button[aria-label*='Enviar' i]",
        ]:
            try:
                for button in self.driver.find_elements(By.CSS_SELECTOR, selector):
                    if button.is_displayed() and button.is_enabled():
                        button.click()
                        sent = True
                        break
                if sent:
                    break
            except Exception:
                pass
        if not sent:
            prompt.send_keys(Keys.ENTER)

        self._sleep(0.8)
        delivered = self._last_user_message_text()
        if delivered and not prompt_delivery_matches(typed_prompt, delivered):
            diagnostic = self._save_diagnostic("prompt_incompleto")
            raise RuntimeError(f"ChatGPT publicó un prompt incompleto. Diagnóstico: {diagnostic}")
        if delivered:
            self.log("[RESEARCH] Prompt enviado y verificado completo.")

        deadline = time.monotonic() + self.response_timeout_seconds
        first_seen = None
        last_text = ""
        stable = 0
        last_state_check = 0.0
        while time.monotonic() < deadline:
            self._check_stop()
            if not self.is_alive():
                raise RuntimeError("Se cerró Edge mientras ChatGPT respondía")
            self._dismiss_soft_overlays()
            text = choose_response_text(self._response_texts(), prompt_text, baseline_norms)
            if not text:
                text = choose_body_response_candidate(self._body_text(), prompt_text)
            if text:
                if looks_conversation_limit(text):
                    raise ChatGPTConversationLimitError(text[:500])
                if looks_transient(text):
                    raise ChatGPTTransientError(text[:500])
                if first_seen is None:
                    first_seen = time.monotonic()
                    self.log("[RESEARCH] Respuesta detectada; esperando que termine...")
                if text == last_text:
                    stable += 1
                else:
                    stable = 0
                    last_text = text
                try:
                    extract_json_object(text)
                    json_complete = True
                except Exception:
                    json_complete = False
                structured_complete = looks_like_complete_seo_response(text)
                elapsed = time.monotonic() - first_seen
                if json_complete and elapsed >= 2.0 and stable >= 2 and not self._stop_button_visible():
                    return text
                if structured_complete and elapsed >= 3.0 and stable >= 2 and not self._stop_button_visible():
                    return text
                if len(text) >= 20 and elapsed >= 6 and stable >= 4 and not self._stop_button_visible():
                    return text

            now = time.monotonic()
            if now - last_state_check >= 3:
                last_state_check = now
                body = self._body_text()
                if looks_conversation_limit(body):
                    raise ChatGPTConversationLimitError("La interfaz indicó límite de conversación")
                if looks_transient(body):
                    raise ChatGPTTransientError("La interfaz indicó límite/error temporal")
                if self._logged_out_header_visible():
                    self.log("[RESEARCH] La sesión se cerró. Espero login y repetiré el mismo SKU.")
                    self._wait_ready()
                    raise ChatGPTConversationLimitError("Login recuperado; reenviar producto")
            self._sleep(1.0)

        diagnostic = self._save_diagnostic("respuesta_timeout")
        raise RuntimeError(f"ChatGPT excedió el tiempo de respuesta. Diagnóstico: {diagnostic}")

    def generate(self, product: dict[str, Any]) -> ResearchSeoResult:
        self.start()
        assert self.driver is not None
        prompt_definition = PromptRegistry.get("SEO_PRODUCTO_STECH_V1")
        prompt = build_research_prompt(product)
        sku = str(product.get("sku") or "").strip()
        name = str(product.get("name") or sku).strip()
        self.log(f"[RESEARCH] Investigando SKU {sku}: {name}")

        raw = ""
        for chat_attempt in range(4):
            self._open_new_chat()
            try:
                raw = self._send_prompt(prompt)
                break
            except ChatGPTConversationLimitError as exc:
                if chat_attempt >= 3:
                    raise RuntimeError(f"No se pudo estabilizar un chat nuevo: {exc}") from exc
                self.log(f"[RESEARCH] Chat no reutilizable ({exc}). Nuevo chat y MISMO SKU.")
                self._sleep(1.2)
        else:
            raise RuntimeError("No se obtuvo respuesta en un chat estable")

        if looks_transient(raw):
            raise ChatGPTTransientError(raw[:500])

        payload = None
        parse_error = None
        for correction in range(3):
            try:
                payload = validate_seo_payload(extract_json_object(raw))
                break
            except Exception as exc:
                parse_error = exc
                if correction >= 2:
                    break
                self.log(f"[RESEARCH] JSON requiere corrección: {exc}")
                raw = self._send_prompt(
                    "Corrige tu respuesta anterior. El problema fue: "
                    + str(exc)
                    + ". Devuelve SOLO el objeto JSON válido con exactamente las claves y 3 FAQ solicitadas; no agregues markdown ni explicación."
                )
        if payload is None:
            raise ValueError(f"No se obtuvo JSON válido después de correcciones: {parse_error}")

        safe_sku = re.sub(r"[^A-Za-z0-9_.-]+", "_", sku or "SIN_SKU")[:90]
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:70]
        stamp = time.strftime("%Y%m%d_%H%M%S")
        raw_path = self.raw_dir / f"{safe_sku}_{safe_name}_{stamp}.json"
        raw_path.write_text(
            json.dumps(
                {
                    "product": {"sku": sku, "name": name, "url": product.get("url", "")},
                    "prompt": {
                        "id": prompt_definition.prompt_id,
                        "version": prompt_definition.version,
                        "sha256": prompt_definition.sha256,
                    },
                    "result": payload,
                    "raw_text": raw,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return ResearchSeoResult(
            payload=payload,
            raw_text=raw,
            raw_path=raw_path,
            prompt_id=prompt_definition.prompt_id,
            prompt_version=prompt_definition.version,
            prompt_hash=prompt_definition.sha256,
        )
