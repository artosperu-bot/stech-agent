from __future__ import annotations

from stech_agent.research.edge_chatgpt import (
    EdgeChatGPTWorker,
    composer_prompt_text,
    prompt_delivery_matches,
)


class RuntimeEdgeChatGPTWorker(EdgeChatGPTWorker):
    """Production Edge worker with environment and composer hardening.

    The V7.2 research contract remains unchanged. Runtime-specific safeguards
    validate Selenium before touching Edge and recover when ChatGPT's current
    contenteditable silently drops a Selenium ``send_keys`` payload.
    """

    def start(self) -> None:
        if self.is_alive():
            return
        # Fail before touching Edge/ports when the local virtualenv is stale.
        self._selenium()
        super().start()

    def _fill_prompt(self, element, prompt_text: str) -> str:
        try:
            return super()._fill_prompt(element, prompt_text)
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
        self.log("[RESEARCH] El compositor descartó send_keys; recuperé el prompt con fallback DOM.")
        return safe_text
