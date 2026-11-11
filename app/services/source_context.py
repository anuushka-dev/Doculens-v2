"""Bound context and retain exactly the text made visible to a model."""

from collections.abc import Sequence

from app.schemas.retrieval import ChunkRecord


def fit_context[T: ChunkRecord](
    chunks: Sequence[T],
    max_chars: int,
) -> tuple[str, tuple[T, ...]]:
    """Return prompt text and the corresponding visible source spans.

    A source ID whose header cannot fit is never admitted. A quote from an
    omitted tail or an omitted chunk must not validate against the full index.
    """
    parts: list[str] = []
    visible: list[T] = []
    used = 0
    for chunk in chunks:
        header = f"[chunk_id={chunk.chunk_id} | page={chunk.page_number}]\n"
        separator = 2 if parts else 0
        remaining = max_chars - used - separator - len(header)
        if remaining <= 0:
            break
        text = chunk.text[:remaining].rstrip()
        if not text:
            break
        values = chunk.model_dump()
        values.update(text=text, end_char=chunk.start_char + len(text))
        visible.append(type(chunk).model_validate(values))
        block = header + text
        parts.append(block)
        used += separator + len(block)
        if len(text) < len(chunk.text):
            break
    return "\n\n".join(parts), tuple(visible)
