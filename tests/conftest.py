import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.llm import AnswerResult  # noqa: E402
from app.main import create_app  # noqa: E402
from app.store import Store  # noqa: E402


class FakeAnswerer:
    """Stands in for Claude. Returns whatever the test queues up and records each call."""

    def __init__(self):
        self.calls = []
        self.next = AnswerResult("answered", "The Growth plan is $49 a month.", [1], 1000, 100)
        self.error = None

    def answer(self, question, history, hits):
        self.calls.append({"question": question, "history": history, "hits": hits})
        if self.error:
            raise self.error
        return self.next


class FakeNotifier:
    def __init__(self, error=None):
        self.leads = []
        self.error = error

    def notify(self, lead):
        if self.error:
            raise self.error
        self.leads.append(lead)


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def make_client(tmp_path):
    def _make(**overrides):
        answerer = overrides.pop("answerer", None) or FakeAnswerer()
        settings = Settings(database_path=tmp_path / "test.sqlite3", **overrides)
        notifier = FakeNotifier()
        store = Store(settings.database_path)
        clock = FakeClock()
        app = create_app(settings, answerer=answerer, notifier=notifier, store=store, clock=clock)
        client = TestClient(app)
        client.answerer, client.notifier, client.store, client.clock, client.settings = (
            answerer, notifier, store, clock, settings)
        return client
    return _make


@pytest.fixture
def client(make_client):
    return make_client()
