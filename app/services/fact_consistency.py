"""A narrow deterministic guard for incompatible numerical source statements.

A model can overlook even two otherwise identical sentences with different
numbers. This guard compares matching question-relevant statements against
proposed citations. It does not detect every paraphrased or contextual conflict.
"""

import re
import unicodedata
from collections.abc import Sequence
from decimal import Decimal

from app.schemas.answer import Citation
from app.schemas.retrieval import RetrievedChunk

_NUMBER = re.compile(r"(?<![\w+-])[+-]?\d+(?:\.\d+)?(?!\w)")
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_STOP = frozenset(
    "the a an what which who how is are was were do does did for in on to of and or about this that pdf document please long many much".split()
)


def _terms(text: str) -> set[str]:
    # Match simple English plural question words such as refund/refunds.
    words = set(_WORD.findall(unicodedata.normalize("NFKC", text).casefold())) - _STOP
    return {
        word[:-3] + "y"
        if len(word) > 4 and word.endswith("ies")
        else word[:-1]
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss")
        else word
        for word in words
    }


def _facts(text: str):
    # Keep source lines separate: a short PDF heading must not become part of
    # the following fact's identity. Identical line fragments may also cause
    # conservative abstention when their wider conditions are ambiguous.
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        normalized = unicodedata.normalize("NFKC", sentence).casefold()
        values = tuple(
            str(Decimal(m.group()).normalize()) for m in _NUMBER.finditer(normalized)
        )
        if not values:
            continue
        signature = tuple(re.findall(r"#|%|[^\W_]+", _NUMBER.sub("#", normalized)))
        words = _terms(normalized)
        if len(words) >= 3:
            yield signature, values, words


def has_numeric_conflict(
    *, citations: Sequence[Citation], chunks: Sequence[RetrievedChunk], question: str
) -> bool:
    question_words = _terms(question)
    required = min(2, len(question_words))
    anchors = {
        signature: values
        for citation in citations
        for signature, values, words in _facts(citation.excerpt)
        if required and len(words & question_words) >= required
    }
    if not anchors:
        return False
    for chunk in chunks:
        for signature, values, _ in _facts(chunk.text):
            if signature in anchors and anchors[signature] != values:
                return True
    return False
