from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from .models import PublicCase


PUBLIC_DIRECTORY = Path(__file__).resolve().parents[4] / "public"
CASES_PATH = PUBLIC_DIRECTORY / "cases.json"
EVIDENCE_ID_PATTERN = re.compile(r"\[([A-Z][A-Z0-9]+(?:-[A-Z0-9]+){2,})\]")


class _CaseRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    id: str
    domain: str
    difficulty: str
    question: str
    context_files: tuple[str, str]

    @field_validator("id", "domain", "difficulty", "question")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("Case fields must be non-empty strings.")
        return value


class _CasePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    cases: tuple[_CaseRecord, ...]

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Dataset version must be positive.")
        return value


def load_public_cases(
    public_directory: Path = PUBLIC_DIRECTORY,
) -> tuple[PublicCase, ...]:
    public_root = public_directory.resolve()
    cases_path = public_root / "cases.json"
    try:
        raw_payload = json.loads(cases_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Public case bank not found: {cases_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Public case bank is invalid JSON: {cases_path}") from exc

    try:
        payload = _CasePayload.model_validate(raw_payload)
    except ValidationError as exc:
        raise ValueError("Public case bank failed schema validation.") from exc

    cases = tuple(_load_case(public_root, case_record) for case_record in payload.cases)
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("Public case bank contains duplicate case IDs.")
    return cases


def _load_case(public_root: Path, record: _CaseRecord) -> PublicCase:
    if len(set(record.context_files)) != len(record.context_files):
        raise ValueError(
            f"Public case {record.id} must use two distinct context files."
        )

    context_parts: list[str] = []
    for relative_path in record.context_files:
        resolved_path = (public_root / relative_path).resolve()
        if not resolved_path.is_relative_to(public_root):
            raise ValueError(
                f"Public case {record.id} contains a context path outside the dataset."
            )
        try:
            content = resolved_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError as exc:
            raise ValueError(
                f"Public case {record.id} context not found: {relative_path}"
            ) from exc
        if not content:
            raise ValueError(
                f"Public case {record.id} context is empty: {relative_path}"
            )
        context_parts.append(f"# Source file: {relative_path}\n\n{content}")

    context = "\n\n---\n\n".join(context_parts)
    evidence_ids = frozenset(EVIDENCE_ID_PATTERN.findall(context))
    if not evidence_ids:
        raise ValueError(f"Public case {record.id} has no evidence IDs in context.")

    return PublicCase(
        id=record.id,
        domain=record.domain,
        difficulty=record.difficulty,
        question=record.question,
        context=context,
        context_files=record.context_files,
        evidence_ids=evidence_ids,
    )
