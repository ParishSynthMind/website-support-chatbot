"""Build the static GitHub Pages copy of the demo into docs/.

The Pages site has no backend, so the widget runs in "recorded" mode and
replays docs/transcript.json, a real conversation captured from the live
server by scripts/record_conversation.py.

    python scripts/build_pages.py
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.main import render_demo_page  # noqa: E402

DOCS = ROOT / "docs"


def main():
    DOCS.mkdir(exist_ok=True)
    if not (DOCS / "transcript.json").exists():
        raise SystemExit("docs/transcript.json is missing: run scripts/record_conversation.py against a live server first.")
    shutil.copy(ROOT / "widget" / "widget.js", DOCS / "widget.js")
    html = render_demo_page(
        note=("Fictional company for a demo. This static copy has no backend, so the chat replays a real "
              "recorded conversation with the live bot. The source, and how to run it live, is on "
              '<a href="https://github.com/ParishSynthMind/website-support-chatbot">GitHub</a>.'),
        widget_tag=('<script src="widget.js" data-company="Orbitly" data-mode="recorded" '
                    'data-transcript="transcript.json" data-open="true" defer></script>'),
        # keep the page text clear of the open chat panel on wide screens
        extra_css="@media (min-width:1000px){.hero,.plans,.note{margin-left:6vw;margin-right:430px;max-width:none}}",
    )
    (DOCS / "index.html").write_text(html, encoding="utf-8")
    (DOCS / ".nojekyll").write_text("")
    print("Wrote docs/index.html, docs/widget.js")


if __name__ == "__main__":
    main()
