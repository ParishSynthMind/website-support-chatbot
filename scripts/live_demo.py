"""Drive the real widget in headless Chrome against a running server,
capture screenshots into media/ and the real transcript into docs/transcript.json.

    python -m app.main                      # in another terminal, with ANTHROPIC_API_KEY set
    python scripts/live_demo.py --base http://127.0.0.1:8000

Needs `pip install playwright` and either Google Chrome installed or
`playwright install chromium` (then pass --bundled-chromium).
"""
import argparse
import json
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "media"
DOCS = ROOT / "docs"

QUESTIONS = [
    "How much is the Growth plan, and how much do I save paying yearly?",
    "If I pay annually and cancel after two weeks, do I get money back?",
    "Can I connect Orbitly to n8n?",
    "Do you have an Android app?",
]
VISITOR = {"name": "Sam Visitor", "email": "sam.visitor@example.com"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--bundled-chromium", action="store_true")
    args = ap.parse_args()
    MEDIA.mkdir(exist_ok=True)
    DOCS.mkdir(exist_ok=True)

    turns, handover = [], None
    with sync_playwright() as p:
        browser = p.chromium.launch(**({} if args.bundled_chromium else {"channel": "chrome"}))
        page = browser.new_page(viewport={"width": 1280, "height": 860}, device_scale_factor=2)
        page.goto(args.base + "/")
        page.click("#support-chat-widget >> css=.launcher")
        widget = page.locator("#support-chat-widget")

        for i, q in enumerate(QUESTIONS, 1):
            box = widget.locator("form.send input")
            box.fill(q)
            with page.expect_response(lambda r: r.url.endswith("/chat")) as resp_info:
                widget.locator("form.send button").click()
            data = resp_info.value.json()
            page.wait_for_function(
                "() => !document.querySelector('#support-chat-widget').shadowRoot.querySelector('.typing')")
            turns.append({"role": "visitor", "text": q})
            turns.append({"role": "assistant", "text": data["reply"], "status": data["status"],
                          "citations": data["citations"], "offer_handover": data["offer_handover"],
                          "handover_reason": data["handover_reason"]})
            print(f"\nVISITOR: {q}\nBOT [{data['status']}]: {data['reply']}")
            for c in data["citations"]:
                print(f"   cited: {c['source']} ({c['heading']})")
            if i == 2:
                page.screenshot(path=str(MEDIA / "widget-answer-with-citations.png"))

        last = turns[-1]
        if last["offer_handover"]:
            widget.locator(".m.a .hbtn").last.click()
            widget.locator(".ho input[name=name]").fill(VISITOR["name"])
            widget.locator(".ho input[name=email]").fill(VISITOR["email"])
            question = widget.locator(".ho textarea").input_value()
            page.screenshot(path=str(MEDIA / "widget-handover-form.png"))
            with page.expect_response(lambda r: r.url.endswith("/handover")) as resp_info:
                widget.locator(".ho .go").click()
            hd = resp_info.value.json()
            page.wait_for_timeout(300)
            page.screenshot(path=str(MEDIA / "widget-handover-done.png"))
            handover = {**VISITOR, "question": question, "reason": last["handover_reason"],
                        "lead_id": hd.get("lead_id"), "response_message": hd.get("message")}
            print(f"\nHANDOVER submitted -> {hd}")

        mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=3,
                                  is_mobile=True, has_touch=True)
        mobile.goto(args.base + "/")
        mobile.click("#support-chat-widget >> css=.launcher")
        mobile.wait_for_timeout(300)
        mobile.screenshot(path=str(MEDIA / "widget-mobile.png"))
        browser.close()

    record = {"recorded_on": date.today().isoformat(), "company": "Orbitly",
              "note": "Real conversation with the live server (Claude Sonnet 5.5), captured by scripts/live_demo.py.",
              "turns": turns, "handover": handover}
    (DOCS / "transcript.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"\nWrote {DOCS / 'transcript.json'} and screenshots in {MEDIA}/")


if __name__ == "__main__":
    main()
