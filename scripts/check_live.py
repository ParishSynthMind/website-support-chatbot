"""Uptime check for a deployed copy of the chatbot. Exits 0 when healthy, 1 with a
plain reason when not, so cron, GitHub Actions or any monitor can alert on it.

    python scripts/check_live.py https://your-app.onrender.com
    python scripts/check_live.py https://your-app.onrender.com --chat   # also asks one real question

Checks: /health answers 200 with ok=true and at least one help-doc section, /widget.js
is served, and with --chat that a pricing question comes back "answered" with a source
from pricing.md. Free hosts sleep when idle, so the first request gets a long timeout."""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

QUESTION = "How much is the Starter plan per month?"


def fetch(url: str, timeout: float, data: dict = None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                         "User-Agent": "chatbot-uptime-check"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def check(base: str, chat: bool, wake_timeout: float = 120) -> list:
    """Return a list of human-readable results; raise AssertionError with the reason on failure."""
    base = base.rstrip("/")
    results = []
    t = time.perf_counter()
    try:
        status, _, raw = fetch(base + "/health", wake_timeout)
    except (urllib.error.URLError, OSError) as exc:
        raise AssertionError(f"/health unreachable: {exc}")
    health = json.loads(raw)
    assert status == 200 and health.get("ok") is True, f"/health returned {status}: {health}"
    assert health.get("sections", 0) > 0, f"/health shows no help-doc sections loaded: {health}"
    results.append(f"/health 200 in {time.perf_counter() - t:.1f}s, provider={health.get('provider')} "
                   f"model={health.get('model')} sections={health['sections']}")

    status, ctype, raw = fetch(base + "/widget.js", 30)
    assert status == 200 and "javascript" in ctype and len(raw) > 1000, f"/widget.js returned {status} {ctype}"
    results.append(f"/widget.js 200, {len(raw)} bytes")

    if chat:
        t = time.perf_counter()
        try:
            status, _, raw = fetch(base + "/chat", 60, {"message": QUESTION, "history": []})
        except urllib.error.HTTPError as exc:
            raise AssertionError(f"/chat returned HTTP {exc.code}")
        body = json.loads(raw)
        assert body.get("status") == "answered", f"/chat did not answer: status={body.get('status')} reply={body.get('reply')!r}"
        assert any(c.get("source") == "pricing.md" for c in body.get("citations", [])), f"/chat answer had no pricing.md source: {body}"
        results.append(f"/chat answered in {time.perf_counter() - t:.1f}s: {body['reply'][:120]}")
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("url")
    ap.add_argument("--chat", action="store_true", help="also send one real question (costs a fraction of a cent)")
    args = ap.parse_args(argv)
    try:
        for line in check(args.url, args.chat):
            print("OK  " + line)
    except AssertionError as exc:
        print(f"FAIL {args.url}: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # anything unexpected is also a failure, never a silent pass
        print(f"FAIL {args.url}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
