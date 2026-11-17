"""AI disclosure (EU AI Act Article 50): every chat starts by saying it is an AI, and so does every handover."""
from pathlib import Path

from app.config import DEFAULT_AI_DISCLOSURE, Settings
from app.llm import AnswerResult

ROOT = Path(__file__).resolve().parent.parent


def ask(client, message, history=None):
    return client.post("/chat", json={"message": message, "history": history or []}).json()


def test_first_turn_carries_the_disclosure_and_later_turns_do_not(client):
    first = ask(client, "How much is the Growth plan per month?")
    assert first["status"] == "answered"
    assert first["ai_disclosure"] == "I'm an AI assistant for Orbitly."
    history = [{"role": "visitor", "text": "How much is the Growth plan per month?"},
               {"role": "assistant", "text": first["reply"]}]
    second = ask(client, "And the Starter plan?", history)
    assert second["ai_disclosure"] is None


def test_a_new_or_resumed_conversation_gets_it_again(client):
    ask(client, "How much is the Growth plan per month?")
    again = ask(client, "How much is the Growth plan per month?")  # reloaded page: no history sent
    assert again["ai_disclosure"] == "I'm an AI assistant for Orbitly."


def test_every_handover_path_discloses(client):
    history = [{"role": "visitor", "text": "hi"}, {"role": "assistant", "text": "hello"}]
    person = ask(client, "Can I talk to a real person?", history)
    assert person["status"] == "handover" and person["ai_disclosure"]
    assert "I'm an AI assistant" in person["reply"]
    unknown = ask(client, "zzqx flurb wibble", history)
    assert unknown["offer_handover"] and unknown["ai_disclosure"]
    client.answerer.next = AnswerResult("needs_human", "Let me get someone.", [], 10, 10)
    needs = ask(client, "Can I get a refund on an annual plan?", history)
    assert needs["status"] == "needs_human" and needs["ai_disclosure"]
    client.answerer.error = RuntimeError("down")
    err = ask(client, "How much is the Growth plan per month?", history)
    assert err["status"] == "unavailable" and err["ai_disclosure"]


def test_handover_confirmation_says_a_person_replies(client):
    r = client.post("/handover", json={"name": "Sam", "email": "sam@example.com", "question": "Refund?"})
    assert "A person on the team" in r.json()["message"]


def test_demo_page_passes_the_disclosure_to_the_widget(client):
    page = client.get("/").text
    assert "data-ai-disclosure=\"I&#x27;m an AI assistant for Orbitly.\"" in page


def test_widget_shows_it_in_the_header_greeting_and_handover_form():
    js = (ROOT / "widget" / "widget.js").read_text()
    assert "\"I'm an AI assistant for \" + cfg.company" in js       # default when no attribute is given
    assert "\"Hi! \" + (cfg.aiDisclosure" in js                     # greeting, live and recorded mode
    assert "AI assistant \\u00b7 answers from our help docs" in js  # header, always visible
    assert "You've been chatting with an AI assistant." in js        # handover form
    assert (ROOT / "docs" / "widget.js").read_text() == js           # GitHub Pages copy is the same file


def test_custom_text_and_company_placeholder(make_client):
    c = make_client(company_name="Harbour Dental", ai_disclosure="You're chatting with {company}'s AI assistant.")
    assert ask(c, "How much is the Growth plan per month?")["ai_disclosure"] == "You're chatting with Harbour Dental's AI assistant."


def test_blank_text_without_a_written_request_falls_back_to_the_default(make_client, monkeypatch):
    c = make_client(ai_disclosure="   ")
    assert ask(c, "How much is the Growth plan per month?")["ai_disclosure"] == "I'm an AI assistant for Orbitly."
    monkeypatch.setenv("AI_DISCLOSURE", "")
    monkeypatch.delenv("AI_DISCLOSURE_REMOVED_BY_WRITTEN_REQUEST", raising=False)
    assert Settings.from_env().disclosure() == DEFAULT_AI_DISCLOSURE.replace("{company}", Settings.from_env().company_name)


def test_only_a_recorded_written_request_removes_it(make_client):
    c = make_client(ai_disclosure_removed_by_written_request="2026-12-01 client email from J. Smith")
    body = ask(c, "How much is the Growth plan per month?")
    assert body["ai_disclosure"] is None
    assert 'data-ai-disclosure=""' in c.get("/").text
