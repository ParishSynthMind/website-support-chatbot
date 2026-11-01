from app.config import Settings
from app.kb import KnowledgeBase, chunk_markdown, tokenize


def kb():
    return KnowledgeBase.from_dir(Settings().knowledge_base_dir)


def test_chunks_by_section_and_keeps_doc_title():
    chunks = chunk_markdown("# Title\nIntro\n\n## Webhooks\nFire on events.", "x.md")
    assert [c.heading for c in chunks] == ["Title", "Webhooks"]
    assert chunks[1].text.startswith("Title\n## Webhooks")


def test_light_stemming_matches_plurals_and_adverbs():
    assert tokenize("Refunds annually") == tokenize("refund annual")


def test_refund_question_finds_the_annual_refund_section():
    headings = [h.chunk.heading for h in kb().search("Can I get a refund on my annual plan?", 5)]
    assert headings[0] == "Refunds for annual plans"


def test_off_topic_question_finds_nothing():
    assert kb().search("What's the weather in Paris?") == []


def test_sources_listed():
    assert kb().sources == ["integrations.md", "pricing.md", "refunds-and-cancellations.md"]
