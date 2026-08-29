from stech_agent.research.runtime_worker import RuntimeEdgeChatGPTWorker


class FakeElement:
    tag_name = "div"

    def __init__(self, text):
        self.text = text

    def get_attribute(self, name):
        if name == "innerText":
            return self.text
        return ""


class FakeDriver:
    def __init__(self, worker, expected):
        self.worker = worker
        self.expected = expected
        self.force_submit_calls = 0

    def execute_script(self, script, element):
        self.force_submit_calls += 1
        element.text = ""
        self.worker._fake_last_user_message = self.expected
        return "button"


class Worker(RuntimeEdgeChatGPTWorker):
    def __init__(self, raw_dir):
        super().__init__(raw_dir=raw_dir)
        self._fake_last_user_message = ""

    def _last_user_message_text(self):
        return self._fake_last_user_message

    def _sleep(self, _seconds):
        pass


def test_stuck_prompt_forces_dom_submit_and_verifies_delivery(tmp_path):
    expected = "PROMPT V7.2 COMPLETO"
    worker = Worker(tmp_path)
    prompt = FakeElement(expected)
    worker.driver = FakeDriver(worker, expected)

    method = worker._ensure_prompt_submitted
    method(prompt, expected, wait_seconds=0)

    assert worker.driver.force_submit_calls == 1
    assert worker._last_user_message_text() == expected
    assert prompt.text == ""
