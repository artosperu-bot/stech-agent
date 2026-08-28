from stech_agent.research.runtime_worker import RuntimeEdgeChatGPTWorker


class FakeElement:
    tag_name = "div"

    def __init__(self):
        self.text = ""
        self.sent = []

    def click(self):
        pass

    def send_keys(self, *values):
        self.sent.append(values)
        # Simula el caso real observado: Selenium envía teclas pero ChatGPT
        # no deja el contenido en el editor.

    def get_attribute(self, name):
        if name == "innerText":
            return self.text
        return ""


class FakeDriver:
    def __init__(self):
        self.script_calls = 0

    def execute_script(self, script, element, text):
        self.script_calls += 1
        element.text = text
        return True


def test_fill_prompt_uses_dom_fallback_when_send_keys_is_dropped(tmp_path, monkeypatch):
    worker = RuntimeEdgeChatGPTWorker(raw_dir=tmp_path)
    worker.driver = FakeDriver()
    element = FakeElement()

    class Keys:
        CONTROL = "CTRL"
        BACKSPACE = "BACKSPACE"

    monkeypatch.setattr(worker, "_selenium", lambda: (None, None, Keys, None))
    monkeypatch.setattr(worker, "_sleep", lambda _seconds: None)

    written = worker._fill_prompt(element, "SKU TEST prompt completo")

    assert written == "SKU TEST prompt completo"
    assert element.text == "SKU TEST prompt completo"
    assert worker.driver.script_calls >= 1
