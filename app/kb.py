"""Knowledge base: chunk markdown docs by section and retrieve with BM25.

The original rag-knowledge-assistant used local sentence-transformer
embeddings. That pulls in PyTorch (over 1 GB), which won't fit a free or
small hosting slot, so this service uses BM25 keyword ranking in plain
Python instead. For a few dozen support docs it finds the right sections
well; swap in an embeddings retriever with the same `search()` method if
the knowledge base grows to thousands of pages.
"""
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import List

STOPWORDS = set(
    """a an and are as at be but by can do does for from get got has have how i if in into is it
    its me my of on or our so that the their them then there these they this to was we what when
    where which who why will with you your yours am any about would could should please hi hello
    much many there's i'm it's""".split()
)


@dataclass
class Chunk:
    source: str
    heading: str
    text: str


@dataclass
class Hit:
    chunk: Chunk
    score: float


def stem(w: str) -> str:
    """Very light suffix stripping so "refunds"/"refunded"/"refund" and
    "annually"/"annual" land on the same term. Not a full stemmer."""
    for suffix, min_len in (("ing", 6), ("ly", 6), ("ed", 5), ("s", 4)):
        if len(w) >= min_len and w.endswith(suffix) and not w.endswith("ss"):
            return w[: -len(suffix)]
    return w


def tokenize(text: str) -> List[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    out = []
    for w in words:
        if len(w) < 2 or w in STOPWORDS:
            continue
        out.append(stem(w))
    return out


def chunk_markdown(text: str, source: str) -> List[Chunk]:
    """Split a markdown doc on '## ' headings. The doc title is kept on every
    chunk so a section like '## Webhooks' still knows it belongs to Integrations."""
    title_match = re.match(r"^#\s+(.+)", text.strip())
    title = title_match.group(1).strip() if title_match else source
    chunks = []
    for section in re.split(r"\n(?=## )", text):
        section = section.strip()
        if not section:
            continue
        heading_match = re.match(r"^#{1,2}\s+(.+)", section)
        heading = heading_match.group(1).strip() if heading_match else title
        body = section if heading == title else f"{title}\n{section}"
        chunks.append(Chunk(source=source, heading=heading, text=body))
    return chunks


class KnowledgeBase:
    def __init__(self, chunks: List[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self._tokens = [tokenize(c.text) for c in chunks]
        self._tf = [Counter(t) for t in self._tokens]
        n = len(chunks)
        self._avgdl = (sum(len(t) for t in self._tokens) / n) if n else 0.0
        df = Counter()
        for toks in self._tokens:
            df.update(set(toks))
        self._idf = {term: math.log(1 + (n - d + 0.5) / (d + 0.5)) for term, d in df.items()}

    @classmethod
    def from_dir(cls, directory: Path) -> "KnowledgeBase":
        chunks: List[Chunk] = []
        for path in sorted(Path(directory).glob("*.md")):
            chunks.extend(chunk_markdown(path.read_text(encoding="utf-8"), path.name))
        if not chunks:
            raise RuntimeError(f"No markdown documents found in {directory}")
        return cls(chunks)

    @property
    def sources(self) -> List[str]:
        return sorted({c.source for c in self.chunks})

    def search(self, query: str, k: int = 4) -> List[Hit]:
        terms = tokenize(query)
        hits = []
        for i, tf in enumerate(self._tf):
            dl = len(self._tokens[i])
            score = 0.0
            for term in terms:
                f = tf.get(term)
                if not f:
                    continue
                idf = self._idf.get(term, 0.0)
                score += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self._avgdl))
            if score > 0:
                hits.append(Hit(self.chunks[i], score))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]
