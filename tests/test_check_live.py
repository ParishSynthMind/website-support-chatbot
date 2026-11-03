"""The uptime script against a real local server (the app with a fake model), so the
pass and fail paths are both proven without a deployment."""
import threading
import time
from types import SimpleNamespace

import pytest
import uvicorn

from app.config import Settings
from app.llm import AnswerResult
from app.main import create_app
from app.store import Store
from scripts import check_live


class Answerer:
    def __init__(self):
        self.result = AnswerResult("answered", "Starter is $19 a month.", [1], 10, 10)

    def answer(self, question, history, hits):
        return self.result


@pytest.fixture
def live_server(tmp_path):
    answerer = Answerer()
    settings = Settings(database_path=tmp_path / "t.sqlite3")
    app = create_app(settings, answerer=answerer, notifier=SimpleNamespace(notify=lambda lead: None),
                     store=Store(settings.database_path))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}", answerer
    server.should_exit = True
    thread.join(5)


def test_healthy_app_passes_including_a_real_question(live_server, capsys):
    url, _ = live_server
    assert check_live.main([url, "--chat"]) == 0
    out = capsys.readouterr().out
    assert "/health 200" in out and "provider=anthropic" in out and "/chat answered" in out


def test_wrong_answer_fails_with_a_reason(live_server, capsys):
    url, answerer = live_server
    answerer.result = AnswerResult("not_in_knowledge_base", "No idea.", [], 10, 10)
    assert check_live.main([url, "--chat"]) == 1
    assert "did not answer" in capsys.readouterr().err


def test_unreachable_host_fails(capsys):
    assert check_live.main(["http://127.0.0.1:9"]) == 1
    assert "unreachable" in capsys.readouterr().err
