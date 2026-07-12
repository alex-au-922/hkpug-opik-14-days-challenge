from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    ValidationError,
    field_validator,
)

from .dataset import PUBLIC_DIRECTORY, load_public_cases
from .models import PublicCase


DIFFICULTY_COUNTS = {"easy": 10, "standard": 30, "hard": 10}
PARTITION_COUNTS = {"discovery": 40, "holdout": 10}
EXPECTED_CASES_PER_DOMAIN = 5
EXPECTED_HOLDOUTS_PER_DOMAIN = 1
EXPECTED_SCHEMA_VERSION = 1
EVIDENCE_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]+(?:-[A-Z0-9]+){2,}$")
INLINE_EVIDENCE_ID_PATTERN = re.compile(r"\[([A-Z][A-Z0-9]+(?:-[A-Z0-9]+){2,})\]")
SUPPORTS_DIR_FD = os.open in os.supports_dir_fd
SUPPORTS_FCHMOD = hasattr(os, "fchmod")
SUPPORTS_NOFOLLOW = hasattr(os, "O_NOFOLLOW")


@dataclass(frozen=True)
class EvaluationReference:
    answer: str
    citations: tuple[str, ...]
    escalate: bool
    key_points: tuple[str, ...]


@dataclass(frozen=True)
class EvaluationRubric:
    required_citation_groups: tuple[tuple[str, ...], ...]
    required_points: tuple[str, ...]
    prohibited_claims: tuple[str, ...]
    non_authoritative_evidence: tuple[str, ...]


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    partition: str
    domain: str
    difficulty: str
    question: str
    context_files: tuple[str, str]
    reference: EvaluationReference
    rubric: EvaluationRubric


@dataclass(frozen=True)
class EvaluationBank:
    schema_version: int
    dataset_version: str
    rubric_version: str
    cases: tuple[EvaluationCase, ...]


class _ReferencePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    answer: str
    citations: tuple[str, ...]
    escalate: StrictBool
    key_points: tuple[str, ...]

    @field_validator("answer")
    @classmethod
    def validate_answer(cls, value: str) -> str:
        if not value:
            raise ValueError("Reference answer must be a non-empty string.")
        if len(value.split()) > 100:
            raise ValueError("Reference answer must contain 100 words or fewer.")
        return value

    @field_validator("citations", "key_points")
    @classmethod
    def validate_non_empty_string_list(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("Reference lists must be non-empty.")
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("Reference lists must contain non-empty strings.")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("Reference lists must not contain duplicates.")
        return tuple(cleaned)


class _RubricPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    required_citation_groups: tuple[tuple[str, ...], ...] = Field(default_factory=tuple)
    required_points: tuple[str, ...] = Field(default_factory=tuple)
    prohibited_claims: tuple[str, ...] = Field(default_factory=tuple)
    non_authoritative_evidence: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("required_citation_groups")
    @classmethod
    def validate_required_citation_groups(
        cls, groups: tuple[tuple[str, ...], ...]
    ) -> tuple[tuple[str, ...], ...]:
        cleaned_groups: list[tuple[str, ...]] = []
        for group in groups:
            cleaned = [value.strip() for value in group]
            if not cleaned or any(not value for value in cleaned):
                raise ValueError("Citation groups must contain non-empty evidence IDs.")
            if len(set(cleaned)) != len(cleaned):
                raise ValueError("Citation groups must not contain duplicates.")
            cleaned_groups.append(tuple(cleaned))
        return tuple(cleaned_groups)

    @field_validator(
        "required_points", "prohibited_claims", "non_authoritative_evidence"
    )
    @classmethod
    def validate_optional_string_lists(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("Rubric lists must contain non-empty strings.")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("Rubric lists must not contain duplicates.")
        return tuple(cleaned)


class _CasePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    case_id: str
    partition: str
    domain: str
    difficulty: str
    question: str
    context_files: tuple[str, str]
    reference: _ReferencePayload
    rubric: _RubricPayload

    @field_validator(
        "case_id", "partition", "domain", "difficulty", "question", mode="after"
    )
    @classmethod
    def validate_non_empty_string(cls, value: str) -> str:
        if not value:
            raise ValueError("Evaluation case string fields must be non-empty.")
        return value

    @field_validator("partition")
    @classmethod
    def validate_partition(cls, value: str) -> str:
        if value not in PARTITION_COUNTS:
            raise ValueError("Evaluation case partition must be discovery or holdout.")
        return value

    @field_validator("context_files")
    @classmethod
    def validate_context_files(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != 2:
            raise ValueError("Evaluation cases must list exactly two context files.")
        if len(set(values)) != len(values):
            raise ValueError("Evaluation cases must use distinct context files.")
        if any(not value for value in values):
            raise ValueError("Evaluation case context files must be non-empty.")
        return values


class _BankPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: StrictInt
    dataset_version: str
    rubric_version: str
    cases: tuple[_CasePayload, ...]

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: int) -> int:
        if value != EXPECTED_SCHEMA_VERSION:
            raise ValueError("Evaluation bank schema_version must be 1.")
        return value

    @field_validator("dataset_version", "rubric_version")
    @classmethod
    def validate_version_string(cls, value: str) -> str:
        if not value:
            raise ValueError(
                "Evaluation bank version fields must be non-empty strings."
            )
        return value

    @field_validator("cases")
    @classmethod
    def validate_cases_non_empty(
        cls, values: tuple[_CasePayload, ...]
    ) -> tuple[_CasePayload, ...]:
        if not values:
            raise ValueError("Evaluation bank cases must not be empty.")
        return values


def load_evaluation_bank(
    path: Path, public_directory: Path = PUBLIC_DIRECTORY
) -> EvaluationBank:
    try:
        raw_payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Evaluation bank not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Evaluation bank is invalid JSON: {path}") from exc
    return _parse_evaluation_bank(raw_payload, public_directory=public_directory)


def build_evaluation_bank(
    input_directory: Path,
    output_path: Path | None = None,
    public_directory: Path = PUBLIC_DIRECTORY,
    repository_root: Path | None = None,
) -> EvaluationBank:
    input_paths = sorted(input_directory.glob("*.json"))
    if not input_paths:
        raise ValueError(
            f"Evaluation bank input directory has no JSON files: {input_directory}"
        )

    payloads = [_read_bank_payload(path) for path in input_paths]
    first_payload = payloads[0]
    for payload in payloads[1:]:
        if payload.schema_version != first_payload.schema_version:
            raise ValueError(
                "All evaluation bank domain files must share one schema version."
            )
        if payload.dataset_version != first_payload.dataset_version:
            raise ValueError(
                "All evaluation bank domain files must share one dataset version."
            )
        if payload.rubric_version != first_payload.rubric_version:
            raise ValueError(
                "All evaluation bank domain files must share one rubric version."
            )

    combined_payload = {
        "schema_version": first_payload.schema_version,
        "dataset_version": first_payload.dataset_version,
        "rubric_version": first_payload.rubric_version,
        "cases": [
            case.model_dump(mode="python")
            for payload in payloads
            for case in payload.cases
        ],
    }
    bank = _parse_evaluation_bank(combined_payload, public_directory=public_directory)
    if output_path is None:
        if repository_root is None:
            raise ValueError(
                "Evaluation bank writes require an explicit repository root."
            )
        output_path = _canonical_output_path(repository_root.resolve())
    _validate_output_path(output_path=output_path, repository_root=repository_root)
    _write_evaluation_bank(output_path, bank)
    return bank


def _read_bank_payload(path: Path) -> _BankPayload:
    try:
        raw_payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Evaluation bank domain file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Evaluation bank domain file is invalid JSON: {path}"
        ) from exc

    try:
        return _BankPayload.model_validate(raw_payload)
    except ValidationError as exc:
        messages = "; ".join(error["msg"] for error in exc.errors())
        raise ValueError(
            f"Evaluation bank domain file failed schema validation: {messages}"
        ) from exc


def _parse_evaluation_bank(
    raw_payload: object, public_directory: Path
) -> EvaluationBank:
    try:
        payload = _BankPayload.model_validate(raw_payload)
    except ValidationError as exc:
        raise ValueError("Evaluation bank failed schema validation.") from exc

    cases = tuple(
        sorted(
            (_build_case(case_payload) for case_payload in payload.cases),
            key=lambda case: case.case_id,
        )
    )
    bank = EvaluationBank(
        schema_version=payload.schema_version,
        dataset_version=payload.dataset_version,
        rubric_version=payload.rubric_version,
        cases=cases,
    )
    _validate_evaluation_bank(bank, public_directory=public_directory)
    return bank


def _build_case(payload: _CasePayload) -> EvaluationCase:
    return EvaluationCase(
        case_id=payload.case_id,
        partition=payload.partition,
        domain=payload.domain,
        difficulty=payload.difficulty,
        question=payload.question,
        context_files=payload.context_files,
        reference=EvaluationReference(
            answer=payload.reference.answer,
            citations=tuple(payload.reference.citations),
            escalate=payload.reference.escalate,
            key_points=tuple(payload.reference.key_points),
        ),
        rubric=EvaluationRubric(
            required_citation_groups=tuple(
                tuple(group) for group in payload.rubric.required_citation_groups
            ),
            required_points=tuple(payload.rubric.required_points),
            prohibited_claims=tuple(payload.rubric.prohibited_claims),
            non_authoritative_evidence=tuple(payload.rubric.non_authoritative_evidence),
        ),
    )


def _validate_evaluation_bank(bank: EvaluationBank, public_directory: Path) -> None:
    public_cases = load_public_cases(public_directory)
    public_questions = {_normalize_text(case.question) for case in public_cases}
    public_domains = {case.domain for case in public_cases}
    allowed_context_file_combinations = _allowed_context_file_combinations(public_cases)

    if len(bank.cases) != 50:
        raise ValueError("Evaluation bank must contain exactly 50 cases.")

    case_ids = {case.case_id for case in bank.cases}
    if len(case_ids) != len(bank.cases):
        raise ValueError("Evaluation bank must contain unique case IDs.")

    normalized_questions: set[str] = set()
    partition_counts = Counter(case.partition for case in bank.cases)
    if dict(partition_counts) != PARTITION_COUNTS:
        raise ValueError(
            "Evaluation bank must contain 40 discovery and 10 holdout cases."
        )

    domain_counts = Counter(case.domain for case in bank.cases)
    if set(domain_counts) != public_domains:
        raise ValueError(
            "Evaluation bank domains must match the public practice domains."
        )
    if any(count != EXPECTED_CASES_PER_DOMAIN for count in domain_counts.values()):
        raise ValueError("Evaluation bank must contain exactly five cases per domain.")

    holdout_domain_counts = Counter(
        case.domain for case in bank.cases if case.partition == "holdout"
    )
    if set(holdout_domain_counts) != public_domains or any(
        count != EXPECTED_HOLDOUTS_PER_DOMAIN
        for count in holdout_domain_counts.values()
    ):
        raise ValueError("Evaluation bank must contain exactly one holdout per domain.")

    difficulty_counts = Counter(case.difficulty for case in bank.cases)
    if dict(difficulty_counts) != DIFFICULTY_COUNTS:
        raise ValueError("Evaluation bank must preserve the 10/30/10 difficulty mix.")

    allowed_difficulties = set(DIFFICULTY_COUNTS)
    for case in bank.cases:
        if case.difficulty not in allowed_difficulties:
            raise ValueError(
                f"Evaluation case {case.case_id} uses an unknown difficulty."
            )

        if case.context_files not in allowed_context_file_combinations.get(
            case.domain, frozenset()
        ):
            raise ValueError(
                "Evaluation case "
                f"{case.case_id} uses a context-file combination not published for "
                f"domain {case.domain}."
            )

        question_key = _normalize_text(case.question)
        if question_key in normalized_questions:
            raise ValueError("Evaluation bank contains duplicate question text.")
        if question_key in public_questions:
            raise ValueError(
                f"Evaluation case {case.case_id} reuses a public practice question."
            )
        normalized_questions.add(question_key)

        evidence_ids = _load_context_evidence_ids(
            public_directory=public_directory,
            case_id=case.case_id,
            context_files=case.context_files,
        )
        _validate_evidence_ids(
            evidence_ids=case.reference.citations,
            allowed_ids=evidence_ids,
            label=(
                f"Evaluation case {case.case_id} reference has unknown citation IDs"
            ),
        )
        for group in case.rubric.required_citation_groups:
            _validate_evidence_ids(
                evidence_ids=group,
                allowed_ids=evidence_ids,
                label=(
                    f"Evaluation case {case.case_id} rubric has unknown citation IDs"
                ),
            )
        _validate_evidence_ids(
            evidence_ids=case.rubric.non_authoritative_evidence,
            allowed_ids=evidence_ids,
            label=(
                "Evaluation case "
                f"{case.case_id} rubric has unknown non-authoritative evidence IDs"
            ),
        )


def _load_context_evidence_ids(
    public_directory: Path, case_id: str, context_files: tuple[str, str]
) -> frozenset[str]:
    public_root = public_directory.resolve()
    context_parts: list[str] = []
    for relative_path in context_files:
        resolved_path = (public_root / relative_path).resolve()
        if not resolved_path.is_relative_to(public_root):
            raise ValueError(
                f"Evaluation case {case_id} contains a context path outside the dataset."
            )
        try:
            content = resolved_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError as exc:
            raise ValueError(
                f"Evaluation case {case_id} references an unknown context file: {relative_path}"
            ) from exc
        if not content:
            raise ValueError(
                f"Evaluation case {case_id} context is empty: {relative_path}"
            )
        context_parts.append(content)

    evidence_ids = frozenset(
        INLINE_EVIDENCE_ID_PATTERN.findall("\n\n".join(context_parts))
    )
    if not evidence_ids:
        raise ValueError(f"Evaluation case {case_id} has no evidence IDs in context.")
    return evidence_ids


def _validate_evidence_ids(
    evidence_ids: Iterable[str],
    allowed_ids: frozenset[str],
    label: str,
) -> None:
    evidence_id_list = list(evidence_ids)
    if len(set(evidence_id_list)) != len(evidence_id_list):
        raise ValueError(f"{label}: duplicate evidence IDs.")
    if any(
        not EVIDENCE_ID_PATTERN.match(evidence_id) for evidence_id in evidence_id_list
    ):
        raise ValueError(f"{label}: invalid evidence ID format.")
    unknown_ids = sorted(set(evidence_id_list) - allowed_ids)
    if unknown_ids:
        raise ValueError(f"{label}: {', '.join(unknown_ids)}")


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def _validate_output_path(
    output_path: Path, repository_root: Path | None
) -> Path | None:
    if repository_root is None:
        raise ValueError("Evaluation bank writes require an explicit repository root.")

    authoritative_root = repository_root.resolve()
    canonical_output_path = _canonical_output_path(authoritative_root)
    absolute_output_path = _absolute_path(output_path)
    if absolute_output_path != canonical_output_path:
        raise ValueError(
            "Evaluation bank output path must be the canonical "
            ".local/evaluation/evaluation_bank.json path under the repository root."
        )

    repository_roots = _repository_roots(canonical_output_path)
    if len(repository_roots) > 1:
        raise ValueError(
            "Refusing to write evaluation bank output through a nested Git repository path."
        )
    if not repository_roots or repository_roots[0] != authoritative_root:
        raise ValueError(
            "Unable to validate evaluation bank output path against the repository root."
        )

    _assert_output_path_is_ignored(
        authoritative_root, canonical_output_path.relative_to(authoritative_root)
    )
    return authoritative_root


def _write_evaluation_bank(path: Path, bank: EvaluationBank) -> None:
    absolute_path = _absolute_path(path)
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _serialize_evaluation_bank(bank)
    descriptor = _open_descriptor_anchored_file(absolute_path)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2))
        handle.write("\n")


def _open_descriptor_anchored_file(path: Path) -> int:
    if not SUPPORTS_NOFOLLOW:
        raise ValueError("Safe evaluation bank writes require O_NOFOLLOW support.")
    if not SUPPORTS_DIR_FD:
        raise ValueError("Safe evaluation bank writes require dir_fd support.")
    if not SUPPORTS_FCHMOD:
        raise ValueError("Safe evaluation bank writes require fchmod support.")

    parent_directory = path.parent
    parent_directory.mkdir(parents=True, exist_ok=True)

    try:
        parent_fd = os.open(
            parent_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
    except OSError as exc:
        raise ValueError(
            "Refusing to write evaluation bank output through a non-regular parent directory."
        ) from exc

    try:
        flags = os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW
        descriptor = os.open(path.name, flags, 0o600, dir_fd=parent_fd)
    except OSError as exc:
        os.close(parent_fd)
        raise ValueError(
            "Refusing to write evaluation bank output because the final path component is unsafe."
        ) from exc

    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError(
                "Refusing to write evaluation bank output because the target is not a regular file."
            )
        os.fchmod(descriptor, 0o600)
    except Exception:
        os.close(descriptor)
        raise
    finally:
        os.close(parent_fd)

    return descriptor


def _serialize_evaluation_bank(bank: EvaluationBank) -> dict[str, object]:
    return {
        "schema_version": bank.schema_version,
        "dataset_version": bank.dataset_version,
        "rubric_version": bank.rubric_version,
        "cases": [
            {
                "case_id": case.case_id,
                "partition": case.partition,
                "domain": case.domain,
                "difficulty": case.difficulty,
                "question": case.question,
                "context_files": list(case.context_files),
                "reference": {
                    "answer": case.reference.answer,
                    "citations": list(case.reference.citations),
                    "escalate": case.reference.escalate,
                    "key_points": list(case.reference.key_points),
                },
                "rubric": {
                    "required_citation_groups": [
                        list(group) for group in case.rubric.required_citation_groups
                    ],
                    "required_points": list(case.rubric.required_points),
                    "prohibited_claims": list(case.rubric.prohibited_claims),
                    "non_authoritative_evidence": list(
                        case.rubric.non_authoritative_evidence
                    ),
                },
            }
            for case in sorted(bank.cases, key=lambda case: case.case_id)
        ],
    }


def _absolute_path(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def _canonical_output_path(repository_root: Path) -> Path:
    return repository_root / ".local" / "evaluation" / "evaluation_bank.json"


def _path_ancestors(path: Path) -> tuple[Path, ...]:
    absolute_path = _absolute_path(path)
    return (absolute_path.parent, *absolute_path.parent.parents)


def _repository_roots(path: Path) -> tuple[Path, ...]:
    roots: list[Path] = []
    seen: set[Path] = set()
    for candidate in _path_ancestors(path):
        completed = subprocess.run(
            ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            continue
        root = Path(completed.stdout.strip()).resolve()
        if root not in seen:
            roots.append(root)
            seen.add(root)
    return tuple(roots)


def _allowed_context_file_combinations(
    public_cases: Iterable[PublicCase],
) -> dict[str, frozenset[tuple[str, str]]]:
    combinations: dict[str, set[tuple[str, str]]] = {}
    for case in public_cases:
        combinations.setdefault(case.domain, set()).add(case.context_files)
    return {domain: frozenset(contexts) for domain, contexts in combinations.items()}


def _assert_output_path_is_ignored(
    repository_root: Path, relative_output_path: Path
) -> None:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repository_root),
            "check-ignore",
            "-v",
            "--non-matching",
            "--no-index",
            "--",
            str(relative_output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 128:
        raise ValueError("Unable to validate evaluation bank output path against git.")
    if completed.returncode not in {0, 1}:
        raise ValueError("Unable to validate evaluation bank output path against git.")

    output_lines = [line for line in completed.stdout.splitlines() if line]
    if not output_lines:
        raise ValueError(
            "Evaluation bank output path is not ignored by the repository."
        )

    last_line = output_lines[-1]
    prefix, _, pathname = last_line.partition("\t")
    if not pathname:
        raise ValueError(
            "Evaluation bank output path is not ignored by the repository."
        )

    source, line_number, pattern = prefix.split(":", 2)
    if source == "" and line_number == "" and pattern == "":
        raise ValueError(
            "Evaluation bank output path is not ignored by the repository."
        )
    if pattern.startswith("!"):
        raise ValueError(
            "Evaluation bank output path is only matched by a negated ignore rule."
        )
    if completed.returncode != 0:
        raise ValueError(
            "Evaluation bank output path is not ignored by the repository."
        )
