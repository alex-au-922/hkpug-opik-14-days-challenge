from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError, field_validator


ANSWER_FIELDS = frozenset({"answer", "citations", "escalate"})
Message = dict[str, str]


@dataclass(frozen=True)
class PublicCase:
    id: str
    domain: str
    difficulty: str
    question: str
    context: str
    context_files: tuple[str, str]
    evidence_ids: frozenset[str]


@dataclass(frozen=True)
class ChallengeAnswer:
    answer: str
    citations: tuple[str, ...]
    escalate: bool


class _AnswerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    answer: str
    citations: list[str]
    escalate: StrictBool

    @field_validator("answer")
    @classmethod
    def validate_answer_text(cls, value: str) -> str:
        if not value:
            raise ValueError("Answer text must be a non-empty string.")
        if len(value.split()) > 100:
            raise ValueError("Answer text must contain 100 words or fewer.")
        return value

    @field_validator("citations")
    @classmethod
    def validate_citations(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("At least one citation is required.")
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("Citations must contain unique non-empty evidence IDs.")
        return cleaned


def validate_answer(case: PublicCase, response: str) -> ChallengeAnswer:
    try:
        raw_payload = json.loads(response)
    except json.JSONDecodeError as exc:
        raise ValueError("Answer must be one valid JSON object.") from exc

    if not isinstance(raw_payload, dict):
        raise ValueError("Answer must be one valid JSON object.")

    try:
        payload = _AnswerPayload.model_validate(raw_payload)
    except ValidationError as exc:
        error_types = {error["type"] for error in exc.errors()}
        if "missing" in error_types or "extra_forbidden" in error_types:
            raise ValueError(
                f"Answer fields must be exactly {sorted(ANSWER_FIELDS)}."
            ) from exc
        if "bool_type" in error_types:
            raise ValueError("Answer escalate field must be a boolean.") from exc
        messages = "; ".join(error["msg"] for error in exc.errors())
        raise ValueError(messages) from exc

    citations = tuple(payload.citations)
    if len(set(citations)) != len(citations):
        raise ValueError("Citations must contain unique non-empty evidence IDs.")

    unknown_citations = sorted(set(citations) - case.evidence_ids)
    if unknown_citations:
        raise ValueError(
            f"Answer contains unknown citation IDs: {', '.join(unknown_citations)}"
        )

    return ChallengeAnswer(
        answer=payload.answer,
        citations=citations,
        escalate=payload.escalate,
    )
