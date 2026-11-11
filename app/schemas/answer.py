"""Strict response contracts for evidence-grounded document Q&A."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class AnswerStatus(StrEnum):
    """Possible outcomes of a grounded Q&A request."""

    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class EvidenceAssessment(BaseModel):
    """A separate, conservative review of the question and source excerpts.

    This is a model assessment, not a mathematical proof of correctness.
    No text from this assessment is returned as a document fact.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Put the short evidence explanation before the final decision. A single
    # verdict avoids internally inconsistent combinations of three flags.
    reason: str = Field(min_length=1, max_length=1_000)
    verdict: Literal["supported", "insufficient_evidence", "conflicting_evidence"]
    supporting_ids: tuple[str, ...] = Field(max_length=8)


class EvidenceSpanSelection(BaseModel):
    """Select application-owned source spans without copying or rewriting text."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    abstain: bool = Field(strict=True)
    evidence_ids: tuple[str, ...] = Field(max_length=8)

    @model_validator(mode="after")
    def abstention_has_no_spans(self) -> "EvidenceSpanSelection":
        if self.abstain and self.evidence_ids:
            raise ValueError("an abstaining selection must not select spans")
        return self


class EvidenceQuoteDraft(BaseModel):
    """Untrusted model output containing a chunk ID and source quote."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str = Field(min_length=1, max_length=80)
    quote: str = Field(min_length=1, max_length=4_000)

    @field_validator("quote")
    @classmethod
    def quote_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("quote must not be blank")
        return value


class AnswerDraft(BaseModel):
    """Model-generated answer before citation verification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: str = Field(min_length=1, max_length=8_000)
    abstain: bool = False

    evidence: tuple[EvidenceQuoteDraft, ...] = Field(
        default_factory=tuple,
        max_length=8,
    )

    @field_validator("answer")
    @classmethod
    def answer_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("answer must not be blank")
        return value

    @model_validator(mode="after")
    def abstention_has_no_claims(self) -> AnswerDraft:
        if self.abstain and self.evidence:
            raise ValueError("an abstaining draft must not cite evidence")
        return self


class EvidenceReference(BaseModel):
    """Application-owned metadata for a Phase 2 retrieved chunk."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str = Field(min_length=1, max_length=80)
    document_id: str = Field(min_length=1, max_length=128)
    file_name: str = Field(min_length=1, max_length=255)

    page_number: int = Field(ge=1, strict=True)

    score: float = Field(
        ge=-1.00001,
        le=1.00001,
        allow_inf_nan=False,
        strict=True,
        description=(
            "Cosine similarity from Phase 2, not a probability of answer correctness."
        ),
    )


class Citation(BaseModel):
    """Verified citation assembled from RetrievedChunk metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    citation_id: str = Field(min_length=1, max_length=80)
    chunk_id: str = Field(min_length=1, max_length=80)
    document_id: str = Field(min_length=1, max_length=128)
    file_name: str = Field(min_length=1, max_length=255)

    page_number: int = Field(ge=1, strict=True)

    excerpt: str = Field(min_length=1, max_length=4_000)

    @field_validator("excerpt")
    @classmethod
    def excerpt_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("citation excerpt must not be blank")
        return value


class AnswerResponse(BaseModel):
    """Final validated Q&A response returned by the API."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: str = Field(min_length=1, max_length=8_000)

    status: AnswerStatus

    citations: tuple[Citation, ...] = Field(
        default_factory=tuple,
        max_length=8,
    )

    evidence_references: tuple[EvidenceReference, ...] = Field(
        default_factory=tuple,
        max_length=20,
    )

    request_id: str | None = Field(
        default=None,
        max_length=64,
    )

    @field_validator("answer")
    @classmethod
    def answer_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("answer must not be blank")
        return value

    @model_validator(mode="after")
    def enforce_answer_citation_invariant(self) -> AnswerResponse:

        if self.status == AnswerStatus.ANSWERED and not self.citations:
            raise ValueError(
                "answered responses require at least one verified citation"
            )

        if self.status != AnswerStatus.ANSWERED and self.citations:
            raise ValueError("non-answered responses must not contain citations")

        citation_ids = [citation.citation_id for citation in self.citations]

        if len(citation_ids) != len(set(citation_ids)):
            raise ValueError("citation IDs must be unique")

        return self
