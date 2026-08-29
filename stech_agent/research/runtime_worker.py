from __future__ import annotations

import time

from stech_agent.research.edge_chatgpt import (
    EdgeChatGPTWorker,
    composer_prompt_text,
    prompt_delivery_matches,
)


class RuntimeEdgeChatGPTWorker(EdgeChatGPTWorker):
    """Production Edge worker with environment and composer hardening.

    The V7.2 research contract remains unchanged. Runtime-specific safeguards
    validate Selenium before touching Edge, recover when ChatGPT's current
    contenteditable silently drops ``send_keys``, and verify that a loaded
    prompt actually leaves the composer before waiting for a response.
    """

    def start(self) -> None:
        if self.is_alive():
            return
        # Fail before touching Edge/ports when the local virtualenv is stale.
        self._selenium()
        super().start()

    def _delivery_text(self) -> str:
        """Read the last posted user message without triggering submit recovery."""
        return super()._last_user_message_text()

    def _wait_for_delivery(self, expected: str, wait_seconds: float) -> bool:
        deadline = time.monotonic() + max(0.0, float(wait_seconds))
        while True:
            delivered = self._delivery_text()
            if delivered and prompt_delivery_matches(expected, delivered):
                return True
            if time.monotonic() >= deadline:
                return False
            self._sleep(0.2)

    def _force_dom_submit(self, prompt_element) -> str:
        if not self.driver:
            return ""
        script = r"""
            const el = arguments[0];
            if (!el) return '';
            const form = el.closest ? el.closest('form') : null;

            // requestSubmit is the closest browser-native equivalent to the
            // user pressing ChatGPT's blue send button and fires submit hooks.
            if (form && typeof form.requestSubmit === 'function') {
                try {
                    form.requestSubmit();
                    return 'requestSubmit';
                } catch (e) {}
            }

            const selectors = [
                "button[data-testid='send-button']",
                "button[type='submit']",
                "button[aria-label*='Send' i]",
                "button[aria-label*='Enviar' i]",
                "button[data-testid*='send' i]"
            ];
            const roots = form ? [form, document] : [document];
            for (const root of roots) {
                for (const selector of selectors) {
                    const button = root.querySelector(selector);
                    if (button && !button.disabled) {
                        try {
                            button.click();
                            return 'button';
                        } catch (e) {}
                    }
                }
            }
            return '';
        """
        try:
            return str(self.driver.execute_script(script, prompt_element) or "")
        except Exception:
            return ""

    def _ensure_prompt_submitted(
        self,
        prompt_element,
        expected: str,
        *,
        wait_seconds: float = 1.5,
    ) -> None:
        """Guarantee that a populated ChatGPT prompt was actually submitted.

        Selenium/ChatGPT can occasionally leave the blue send button active
        while the text remains in the composer. In that state the base worker
        would otherwise wait for a response that can never arrive.
        """
        if self._wait_for_delivery(expected, wait_seconds):
            return

        current = self._composer_value(prompt_element)
        if current and not prompt_delivery_matches(expected, current):
            diagnostic = self._save_diagnostic("prompt_cambio_antes_submit")
            raise RuntimeError(
                "El compositor de ChatGPT cambió antes de enviar el prompt. "
                f"Diagnóstico: {diagnostic}"
            )

        # If the text is still there, the native click/Enter did not submit it.
        if current and prompt_delivery_matches(expected, current):
            self.log("[RESEARCH] El prompt quedó en el compositor; forzando envío por DOM/formulario...")
            method = self._force_dom_submit(prompt_element)
            if not method:
                diagnostic = self._save_diagnostic("submit_no_encontrado")
                raise RuntimeError(
                    "ChatGPT dejó el prompt escrito pero no encontré una forma segura de enviarlo. "
                    f"Diagnóstico: {diagnostic}"
                )
            if self._wait_for_delivery(expected, 4.0):
                self.log(f"[RESEARCH] Prompt enviado y verificado mediante {method}.")
                return

            diagnostic = self._save_diagnostic("submit_no_confirmado")
            raise RuntimeError(
                "ChatGPT mantuvo el prompt sin confirmar el envío después del reintento. "
                f"Diagnóstico: {diagnostic}"
            )

        # Composer empty normally means the native send already happened but
        # the user message node has not appeared yet. Give the UI one final,
        # short opportunity before falling back to the base response watcher.
        self._wait_for_delivery(expected, 1.0)

    def _last_user_message_text(self) -> str:
        delivered = self._delivery_text()
        expected = str(getattr(self, "_pending_prompt_text", "") or "")
        if not expected:
            return delivered
        if delivered and prompt_delivery_matches(expected, delivered):
            self._pending_prompt_text = ""
            return delivered

        prompt = self._prompt_element()
        if prompt is None:
            return delivered
        current = self._composer_value(prompt)
        if current and prompt_delivery_matches(expected, current):
            # The base worker already tried its normal click/Enter and waited
            # briefly before calling us. If the full text is still visible,
            # reproduce the user's observed screenshot case and recover now.
            self._ensure_prompt_submitted(prompt, expected, wait_seconds=0)
            delivered = self._delivery_text()
            if delivered and prompt_delivery_matches(expected, delivered):
                self._pending_prompt_text = ""
            return delivered
        return delivered

    def _fill_prompt(self, element, prompt_text: str) -> str:
        try:
            written = super()._fill_prompt(element, prompt_text)
            self._pending_prompt_text = written
            return written
        except RuntimeError as exc:
            if "no recibió el prompt completo" not in str(exc):
                raise

        safe_text = composer_prompt_text(prompt_text)
        if not self.driver:
            raise RuntimeError("ChatGPT perdió el prompt y no hay sesión Edge activa para recuperarlo")

        script = r"""
            const el = arguments[0];
            const text = arguments[1];
            el.focus();

            // First try the browser editing command because it behaves like a
            // real edit in contenteditable/ProseMirror-style composers.
            let inserted = false;
            try {
                const selection = window.getSelection();
                const range = document.createRange();
                range.selectNodeContents(el);
                selection.removeAllRanges();
                selection.addRange(range);
                inserted = document.execCommand('insertText', false, text);
            } catch (e) {}

            // If the UI swallowed execCommand, set the underlying control and
            // dispatch input/change so React sees the new value.
            const current = (el.value || el.innerText || el.textContent || '').trim();
            if (!inserted || !current) {
                if ('value' in el && (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT')) {
                    const descriptor = Object.getOwnPropertyDescriptor(
                        Object.getPrototypeOf(el), 'value'
                    );
                    if (descriptor && descriptor.set) descriptor.set.call(el, text);
                    else el.value = text;
                } else {
                    el.textContent = '';
                    const p = document.createElement('p');
                    p.textContent = text;
                    el.appendChild(p);
                }
                try {
                    el.dispatchEvent(new InputEvent('input', {
                        bubbles: true,
                        inputType: 'insertText',
                        data: text
                    }));
                } catch (e) {
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                }
                el.dispatchEvent(new Event('change', {bubbles: true}));
            }
            return true;
        """

        target = element
        try:
            self.driver.execute_script(script, target, safe_text)
        except Exception:
            # The DOM may have re-rendered between send_keys and verification.
            # Reacquire the visible composer once and retry on the fresh node.
            target = self._prompt_element()
            if target is None:
                raise RuntimeError("ChatGPT reemplazó el compositor y no pude recuperarlo")
            self.driver.execute_script(script, target, safe_text)

        self._sleep(0.25)
        written = self._composer_value(target)
        if not prompt_delivery_matches(safe_text, written):
            raise RuntimeError(
                "ChatGPT no recibió el prompt completo ni con el fallback DOM "
                f"({len(written.strip())}/{len(safe_text.strip())} caracteres)."
            )
        self._pending_prompt_text = safe_text
        self.log("[RESEARCH] El compositor descartó send_keys; recuperé el prompt con fallback DOM.")
        return safe_text
