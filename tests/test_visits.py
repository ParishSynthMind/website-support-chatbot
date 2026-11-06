"""The demo's visit counter: what it records, what it keeps out, and the protected /stats feed."""
import json

from app.visits import VisitLog, clean_src, referrer_parts, ua_class

CHROME = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"


def events(client):
    path = client.app.state.visits.path
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_user_agent_classes():
    assert ua_class(CHROME) == "desktop"
    assert ua_class(IPHONE) == "mobile"
    assert ua_class("NeoUptime/1.0") == "monitor"
    assert ua_class("neo-keepalive") == "monitor"
    assert ua_class("Render/1.0") == "monitor"
    assert ua_class("Mozilla/5.0 (compatible; Googlebot/2.1)") == "bot"
    assert ua_class("Mozilla/5.0 (X11; Linux x86_64) HeadlessChrome/130.0") == "bot"
    assert ua_class("curl/8.4.0") == "bot"
    assert ua_class("") == "unknown"


def test_src_tags_are_cleaned_and_referrers_cut_to_the_domain():
    assert clean_src("Proposal-71") == "proposal-71"
    assert clean_src("<script>") == "other"
    assert clean_src("") == ""
    assert referrer_parts("https://www.upwork.com/freelancers/abc?x=1") == ("www.upwork.com", "")
    assert referrer_parts("https://demo.example/?src=pph") == ("demo.example", "pph")


def test_page_widget_and_chat_are_counted_without_personal_data(client):
    client.get("/?src=upwork-portfolio", headers={"user-agent": CHROME, "referer": "https://www.upwork.com/x"})
    client.get("/widget.js", headers={"user-agent": CHROME, "referer": "http://testserver/?src=upwork-portfolio"})
    client.post("/chat", json={"message": "How much is the Growth plan?", "history": []},
                headers={"user-agent": CHROME, "referer": "http://testserver/?src=upwork-portfolio",
                         "x-forwarded-for": "203.0.113.9"})
    client.get("/health", headers={"user-agent": CHROME})
    got = events(client)
    assert [e["path"] for e in got] == ["/", "/widget.js", "/chat"]  # /health is never counted
    assert all(e["src"] == "upwork-portfolio" and e["ua"] == "desktop" for e in got)
    assert got[0]["ref"] == "www.upwork.com" and got[1]["ref"] == ""  # own domain dropped
    raw = client.app.state.visits.path.read_text()
    assert "203.0.113.9" not in raw and "Chrome/130" not in raw
    assert set(got[0]) == {"id", "ts", "path", "src", "ref", "ua"}


def test_our_uptime_check_is_marked_as_a_monitor(client):
    client.get("/widget.js", headers={"user-agent": "NeoUptime/1.0"})
    assert events(client)[0]["ua"] == "monitor"


def test_stats_is_off_without_a_token(client):
    assert client.get("/stats").status_code == 404


def test_stats_needs_the_token_and_filters_by_time(make_client):
    client = make_client(stats_token="s3cret-token")
    client.get("/?src=pph", headers={"user-agent": IPHONE})
    assert client.get("/stats").status_code == 401
    assert client.get("/stats", headers={"authorization": "Bearer wrong"}).status_code == 401
    r = client.get("/stats", headers={"authorization": "Bearer s3cret-token"})
    assert r.status_code == 200
    (event,) = r.json()["events"]
    assert event["src"] == "pph" and event["ua"] == "mobile"
    later = client.get("/stats", params={"since": "2999-01-01T00:00:00Z"},
                       headers={"authorization": "Bearer s3cret-token"})
    assert later.json()["events"] == []


def test_a_broken_store_never_breaks_the_page(client, tmp_path):
    client.app.state.visits.path = tmp_path / "a-dir"
    (tmp_path / "a-dir").mkdir()
    assert client.get("/").status_code == 200


def test_since_skips_corrupt_lines(tmp_path):
    log = VisitLog(tmp_path / "v.jsonl", clock=lambda: 0)
    log.record("/", "x", "", CHROME)
    with log.path.open("a") as f:
        f.write("not json\n")
    assert [e["src"] for e in log.since()] == ["x"]
