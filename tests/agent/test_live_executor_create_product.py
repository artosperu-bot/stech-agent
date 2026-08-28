from __future__ import annotations

from stech_agent.agent.live_executor import StechLiveExecutor


class FakeSession:
    def __init__(self):
        self.starts = 0

    def start(self):
        self.starts += 1
        return self


class FakeCatalogRepository:
    pass


def test_live_executor_create_product_reuses_existing_session(monkeypatch, tmp_path):
    session = FakeSession()
    transfer_calls = []
    creator_calls = []

    class FakeTransfer:
        def __init__(self, got_session, catalog_repository):
            transfer_calls.append((got_session, catalog_repository))

    class FakeCreator:
        def __init__(self, **kwargs):
            creator_calls.append(kwargs)

        def create(self, values, *, session_id=None):
            return {"status": "VERIFIED", "sku": values["sku"], "created": True}

    monkeypatch.setattr("stech_agent.stech.catalog_transfer.CatalogTransfer", FakeTransfer)
    monkeypatch.setattr("stech_agent.agent.product_create_executor.ProductCreateExecutor", FakeCreator)

    repo = FakeCatalogRepository()
    executor = StechLiveExecutor(session=session)
    result = executor.create_product(
        db=object(),
        catalog_repository=repo,
        values={"sku": "NEW-1"},
        work_dir=tmp_path,
        session_id=4,
    )

    assert result["status"] == "VERIFIED"
    assert session.starts == 1
    assert transfer_calls[0] == (session, repo)
    assert creator_calls[0]["work_dir"] == tmp_path
