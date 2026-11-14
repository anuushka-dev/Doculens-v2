"""Page-local semantic search combined with BM25 keyword retrieval.

Dense similarity can miss exact identifiers, numbers and rare technical terms.
BM25 complements it; neither ranking score establishes answer correctness.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from functools import lru_cache
from threading import RLock

from app.adapters.embeddings.sentence_transformer import SentenceTransformerEmbedder
from app.schemas.retrieval import ChunkRecord, RetrievalResponse, RetrievedChunk
from app.services.page_chunker import PageLike, chunk_pages
from app.services.retrieval_pipeline import NoChunksToIndexError

_STOP = frozenset(
    "a an the is are was were be been it its this that of to in on at for from and or with what which how when where who does do did can could should would about please explain tell me according pdf document".split()
)
_TOKEN = re.compile(r"[^\W_]+(?:[-.][^\W_]+)*", re.UNICODE)

_CONCEPT_SYNONYMS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bproblem(?:\s+statement)?\b", re.IGNORECASE),
        "problem goal scope objective purpose baseline build decision",
    ),
    (
        re.compile(r"\blimit(?:s|ations?)?\b", re.IGNORECASE),
        "limit limits limitations scope boundary boundaries non-goals constraint constraints maximum max cap threshold pages mib bytes characters",
    ),
    (
        re.compile(r"\bboundar(?:y|ies)\b", re.IGNORECASE),
        "boundary limit scope constraints release",
    ),
    (
        re.compile(r"\broadmap\b", re.IGNORECASE),
        "roadmap phase phases milestone deliverable exit gate",
    ),
    (
        re.compile(r"\b(?:setup|install|deploy(?:ment)?)\b", re.IGNORECASE),
        "setup install docker compose uvicorn ollama environment",
    ),
    (
        re.compile(r"\b(?:architecture|system\s+flow)\b", re.IGNORECASE),
        "architecture flow pipeline retrieval ingestion verification",
    ),
)


_BROAD_QUERY_RE = re.compile(
    r"\b(overview|summari[sz]e|summary|main (?:areas|topics)|"
    r"what.{0,60}(?:cover|about)|which.{0,40}areas|scope|purpose|"
    r"problem(?:\s+statement)?|goal|objective|limit(?:s|ations?)?|"
    r"boundar(?:y|ies)|constraint(?:s)?|non-goals|roadmap|architecture)\b",
    flags=re.IGNORECASE,
)
_OVERVIEW_HEADING_RE = re.compile(
    r"(?im)^\s*(abstract|executive summary|introduction|overview|"
    r"problem(?:\s+statement)?|scope|explicitly out of scope|out of scope|"
    r"purpose|the build decision|hard boundary|default limits|limitations|"
    r"non-goals|roadmap at a glance)\b"
)


def _expand_lexical_query(query: str) -> str:
    extras = [
        addition
        for pattern, addition in _CONCEPT_SYNONYMS
        if pattern.search(query)
    ]
    if not extras:
        return query
    return f"{query} {' '.join(extras)}"


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.casefold()) if t not in _STOP]


class BM25Index:
    def __init__(self, records: Sequence[ChunkRecord]) -> None:
        self.counts = tuple(Counter(tokens(r.text)) for r in records)
        self.lengths = tuple(sum(c.values()) for c in self.counts)
        self.average = sum(self.lengths) / max(1, len(records)) or 1
        self.df = Counter(term for row in self.counts for term in row)

    def scores(self, query: str) -> list[float]:
        result = []
        for row, length in zip(self.counts, self.lengths, strict=True):
            score = 0.0
            for term in set(tokens(query)):
                tf = row.get(term, 0)
                if not tf:
                    continue
                frequency = self.df[term]
                idf = math.log(
                    1 + (len(self.counts) - frequency + 0.5) / (frequency + 0.5)
                )
                score += (
                    idf * tf * 2.5 / (tf + 1.5 * (0.25 + 0.75 * length / self.average))
                )
            result.append(score)
        return result


class SharedEmbedder:
    """Share CPU model weights, but serialize loading and encoder inference."""

    def __init__(self) -> None:
        self.model = SentenceTransformerEmbedder(device="cpu")
        self.lock = RLock()

    def embed_texts(self, texts: Sequence[str]):
        with self.lock:
            return self.model.embed_texts(texts)

    def embed_query(self, query: str):
        with self.lock:
            return self.model.embed_query(query)


@lru_cache(maxsize=1)
def shared_embedder() -> SharedEmbedder:
    return SharedEmbedder()


class HybridRetrievalPipeline:
    """An immutable per-document index; safe for simultaneous read-only queries.

    `hybrid` is the product default. `lexical` is an explicit offline option,
    never a silent fallback when the semantic model is unavailable.
    """

    def __init__(self, *, mode: str = "hybrid", embedder=None) -> None:
        if mode not in {"hybrid", "lexical"}:
            raise ValueError("mode must be hybrid or lexical")
        self.mode = mode
        self.embedder = embedder
        self.records: tuple[ChunkRecord, ...] = ()
        self.vectors = None
        self.lexical = None

    def index_pages(
        self, pages: Sequence[PageLike], *, document_id: str, file_name: str
    ) -> tuple[ChunkRecord, ...]:
        if self.records:
            raise ValueError("this document is already indexed")
        # MiniLM truncates at 256 word pieces. Shorter windows reduce the risk;
        # the embedding adapter additionally encodes all overflow windows.
        records = tuple(
            chunk_pages(
                pages,
                document_id=document_id,
                file_name=file_name,
                chunk_size_words=100,
                overlap_words=25,
            )
        )
        if not records:
            raise NoChunksToIndexError("no non-empty chunks were produced")
        vectors = None
        if self.mode == "hybrid":
            self.embedder = self.embedder or shared_embedder()
            vectors = self.embedder.embed_texts([r.text for r in records])
        self.lexical = BM25Index(records)
        self.vectors = vectors
        self.records = records
        return records

    def search(self, query: str, *, top_k: int | None = None) -> RetrievalResponse:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must not be blank")
        k = 8 if top_k is None else top_k
        if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 20:
            raise ValueError("top_k must be between 1 and 20")
        if not self.records:
            raise ValueError("cannot search an empty index")
        raw = self.lexical.scores(_expand_lexical_query(query))
        # Saturation keeps BM25 in the same bounded ranking range as cosine.
        lexical = [score / (score + 1) for score in raw]
        dense = [0.0] * len(raw)
        if self.mode == "hybrid":
            query_vector = self.embedder.embed_query(query)
            dense = [max(0.0, min(1.0, float(x))) for x in self.vectors @ query_vector]
        scores = [
            0.6 * d + 0.4 * lexical_score if self.mode == "hybrid" else lexical_score
            for d, lexical_score in zip(dense, lexical, strict=True)
        ]
        ranked = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
        result = []
        for i in ranked:
            if scores[i] <= 0:
                continue
            candidate = self.records[i]
            # Avoid wasting the context budget on largely duplicate windows.
            if any(
                r.page_number == candidate.page_number
                and max(
                    0,
                    min(r.end_char, candidate.end_char)
                    - max(r.start_char, candidate.start_char),
                )
                > 0.65 * min(len(r.text), len(candidate.text))
                for r in result
            ):
                continue
            result.append(
                RetrievedChunk(**candidate.model_dump(), score=float(scores[i]))
            )
            if len(result) == k:
                break
        return RetrievalResponse(query=query, top_k=k, results=tuple(result))

    def search_evidence(
        self, query: str, *, top_k: int | None = None
    ) -> RetrievalResponse:
        """Add bounded overview and adjacent-page context to top-ranked hits.

        Expansion is a coverage heuristic, never proof that a source answers a
        question. Expanded passages still pass exact-quote and relevance checks.
        Scores for expansions reflect their source seed, not cosine similarity.
        """
        initial = self.search(query, top_k=top_k)
        selected = list(initial.results)
        idx_by_id = {c.chunk_id: idx for idx, c in enumerate(selected)}

        def add(record: ChunkRecord, score: float):
            existing_idx = idx_by_id.get(record.chunk_id)
            if existing_idx is not None:
                if score > selected[existing_idx].score:
                    selected[existing_idx] = RetrievedChunk(
                        **record.model_dump(), score=float(score)
                    )
                return
            if len(selected) < 20:
                idx_by_id[record.chunk_id] = len(selected)
                selected.append(
                    RetrievedChunk(**record.model_dump(), score=float(score))
                )

        if _BROAD_QUERY_RE.search(query):
            base_score = (
                max(0.3, initial.results[0].score * 0.98) if initial.results else 0.3
            )
            matched_heading_records = [
                r
                for r in self.records
                if r.page_number <= 10 and _OVERVIEW_HEADING_RE.search(r.text)
            ]
            overview_pages = {r.page_number for r in matched_heading_records}
            if not overview_pages:
                overview_pages = set(sorted({r.page_number for r in self.records})[:2])
            for r in matched_heading_records:
                add(r, base_score)
            # First two windows preserve titles and abstract paragraphs without
            # filling the prompt with every page of the introduction.
            for r in self.records:
                if r.page_number in overview_pages and r.chunk_index < 2:
                    add(r, base_score * 0.99)

        seed_pages = []
        for seed in initial.results:
            if seed.page_number not in seed_pages:
                seed_pages.append(seed.page_number)
            if len(seed_pages) >= 3:
                break
        for page in seed_pages:
            seed_score = max(c.score for c in initial.results if c.page_number == page)
            head = [r for r in self.records if r.page_number == page and r.chunk_index == 0]
            following = [r for r in self.records if r.page_number == page + 1]
            preceding = [r for r in self.records if r.page_number == page - 1]
            for r in head + following[:2] + preceding[-1:]:
                add(r, seed_score * 0.95)
        selected.sort(key=lambda c: -c.score)
        return RetrievalResponse(query=query, top_k=20, results=tuple(selected))
