from pathlib import Path

from stech_agent.stech.session import StechSession, stech_profile_dir


class FakePage:
    def __init__(self): self.default_timeout = None
    def set_default_timeout(self, value): self.default_timeout = value


class FakeContext:
    def __init__(self): self.pages = [FakePage()]; self.closed = False
    def new_page(self): return self.pages[0]
    def close(self): self.closed = True


class FakeChromium:
    def __init__(self): self.calls = []; self.context = FakeContext()
    def launch_persistent_context(self, **kwargs): self.calls.append(kwargs); return self.context


class FakePW:
    def __init__(self): self.chromium = FakeChromium(); self.stopped = False
    def stop(self): self.stopped = True


def test_profile_is_dedicated_to_new_agent(tmp_path):
    assert stech_profile_dir(tmp_path) == tmp_path / "profiles" / "stech_chrome"


def test_session_start_uses_persistent_profile_and_close_owned_context(tmp_path):
    pw = FakePW(); session = StechSession(app_root=tmp_path, playwright_starter=lambda: pw, auto_navigate=False, slow_mo=0)
    session.start(); call = pw.chromium.calls[0]
    assert Path(call["user_data_dir"]) == tmp_path / "profiles" / "stech_chrome"
    assert call["headless"] is False and session.page.default_timeout == 25_000
    session.close(); assert pw.chromium.context.closed is True and pw.stopped is True


def test_start_is_idempotent(tmp_path):
    pw = FakePW(); session = StechSession(app_root=tmp_path, playwright_starter=lambda: pw, auto_navigate=False, slow_mo=0)
    session.start(); session.start(); assert len(pw.chromium.calls) == 1
