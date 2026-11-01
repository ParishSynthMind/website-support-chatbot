"""Handover flow: lead capture, SQLite storage and the notifiers."""
import sqlite3
import time

import pytest

from app.config import Settings
from app.llm import AnswerResult
from app.main import create_app
from app.notifiers import (ConsoleNotifier, SlackWebhookNotifier, SMTPNotifier, format_lead,
                           make_notifier)
from app.store import Store
from tests.conftest import FakeAnswerer, FakeNotifier

LEAD = {"name": "Dana Example", "email": "dana@example.com",
        "question": "Do you have an Android app?", "reason": "not_in_knowledge_base"}


def test_full_flow_unknown_question_then_handover_is_stored_and_notified(client):
    client.answerer.next = AnswerResult("not_in_knowledge_base", "I don't have that in our docs.", [], 10, 10)
    chat = client.post("/chat", json={"message": "Do you have an Android app for integrations?"}).json()
    assert chat["offer_handover"] is True

    transcript = [{"role": "visitor", "text": "Do you have an Android app for integrations?"},
                  {"role": "assistant", "text": chat["reply"]}]
    r = client.post("/handover", json={**LEAD, "reason": chat["handover_reason"], "transcript": transcript})
    body = r.json()
    assert r.status_code == 200 and body["ok"] is True
    assert "dana@example.com" in body["message"]

    # Stored in a real SQLite file, readable by anything else.
    row = sqlite3.connect(str(client.settings.database_path)).execute(
        "SELECT name, email, question, reason, notified FROM leads WHERE id = ?", (body["lead_id"],)).fetchone()
    assert row == ("Dana Example", "dana@example.com", "Do you have an Android app?", "not_in_knowledge_base", 1)

    assert len(client.notifier.leads) == 1
    sent = client.notifier.leads[0]
    assert sent["id"] == body["lead_id"] and sent["transcript"] == transcript


@pytest.mark.parametrize("email", ["not-an-email", "a@b", "two@@example.com", "spaces in@example.com"])
def test_bad_email_is_rejected_and_nothing_stored(client, email):
    r = client.post("/handover", json={**LEAD, "email": email})
    assert r.status_code == 422
    assert client.store.count_leads() == 0


def test_missing_fields_rejected(client):
    assert client.post("/handover", json={"email": "dana@example.com", "question": "x"}).status_code == 422
    assert client.post("/handover", json={**LEAD, "name": "   "}).status_code == 422


def test_failed_notification_keeps_the_lead(tmp_path):
    settings = Settings(database_path=tmp_path / "db.sqlite3")
    store = Store(settings.database_path)
    app = create_app(settings, answerer=FakeAnswerer(), notifier=FakeNotifier(error=OSError("SMTP down")), store=store)
    from fastapi.testclient import TestClient

    r = TestClient(app).post("/handover", json=LEAD)
    assert r.status_code == 200
    lead = store.get_lead(r.json()["lead_id"])
    assert lead["notified"] == 0 and "SMTP down" in lead["notify_error"]


def test_handover_rate_limited(client):
    for _ in range(3):
        assert client.post("/handover", json=LEAD).status_code == 200
    assert client.post("/handover", json=LEAD).status_code == 429


def test_console_notifier_prints_the_lead(capsys):
    ConsoleNotifier("Orbitly").notify({**LEAD, "id": 7, "transcript": [{"role": "visitor", "text": "hi"}]})
    out = capsys.readouterr().out
    assert "lead #7" in out and "dana@example.com" in out and "visitor: hi" in out


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.calls, self.sent = host, port, [], []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        self.calls.append("starttls")

    def login(self, u, p):
        self.calls.append(("login", u))

    def send_message(self, msg):
        self.sent.append(msg)


def test_smtp_notifier_uses_tls_login_and_reply_to_visitor():
    n = SMTPNotifier("Orbitly", "smtp.example.com", 587, "bot@example.com", "app-password", True,
                     "bot@example.com", "support@example.com", smtp_factory=FakeSMTP)
    n.notify({**LEAD, "id": 3, "transcript": []})
    smtp = FakeSMTP.instances[-1]
    assert (smtp.host, smtp.port) == ("smtp.example.com", 587)
    assert smtp.calls == ["starttls", ("login", "bot@example.com")]
    msg = smtp.sent[0]
    assert msg["To"] == "support@example.com" and msg["Reply-To"] == "dana@example.com"
    assert "Handover from Dana Example" in msg["Subject"]


def test_smtp_notifier_needs_config():
    with pytest.raises(ValueError):
        make_notifier(Settings(notifier="smtp"))


def test_smtp_end_to_end_against_a_real_local_smtp_server(tmp_path):
    """Starts a real SMTP server on localhost (aiosmtpd) and sends a handover through it."""
    aiosmtpd = pytest.importorskip("aiosmtpd.controller")
    received = []

    class Handler:
        async def handle_DATA(self, server, session, envelope):
            received.append(envelope)
            return "250 OK"

    import socket

    with socket.socket() as s:  # find a free port
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    controller = aiosmtpd.Controller(Handler(), hostname="127.0.0.1", port=port)
    controller.start()
    try:
        settings = Settings(database_path=tmp_path / "db.sqlite3", notifier="smtp", smtp_host="127.0.0.1",
                            smtp_port=port, smtp_use_tls=False, smtp_from="bot@example.com",
                            smtp_to="support@example.com")
        from fastapi.testclient import TestClient

        r = TestClient(create_app(settings, answerer=FakeAnswerer())).post("/handover", json=LEAD)
        assert r.status_code == 200
        for _ in range(50):
            if received:
                break
            time.sleep(0.05)
    finally:
        controller.stop()
    assert received and received[0].rcpt_tos == ["support@example.com"]
    assert b"Dana Example" in received[0].content and b"Reply-To: dana@example.com" in received[0].content


def test_slack_notifier_is_a_stub_that_fails_loudly():
    n = make_notifier(Settings(notifier="slack", slack_webhook_url="https://hooks.slack.com/services/XXX"))
    assert isinstance(n, SlackWebhookNotifier)
    assert "dana@example.com" in n.build_payload({**LEAD, "id": 1, "transcript": []})["text"]
    with pytest.raises(NotImplementedError):
        n.notify({**LEAD, "id": 1, "transcript": []})


def test_unknown_notifier_rejected():
    with pytest.raises(ValueError):
        make_notifier(Settings(notifier="carrier-pigeon"))


def test_format_lead_handles_empty_transcript():
    assert "(none)" in format_lead({**LEAD, "id": 1, "transcript": []}, "Orbitly")
