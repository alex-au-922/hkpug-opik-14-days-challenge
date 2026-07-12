from __future__ import annotations

import hashlib
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
EVIDENCE_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]+(?:-[A-Z0-9]+){2,}$")
EXPECTED_SCHEMA_VERSION = 1
EXPECTED_VARIANTS_PER_FAMILY = 8
SUPPORTS_DIR_FD = os.open in os.supports_dir_fd
SUPPORTS_NOFOLLOW = hasattr(os, "O_NOFOLLOW")
SUPPORTS_FCHMOD = hasattr(os, "fchmod")


@dataclass(frozen=True)
class HiddenReference:
    answer: str
    citations: tuple[str, ...]
    escalate: bool
    key_points: tuple[str, ...]


@dataclass(frozen=True)
class HiddenRubric:
    required_citation_groups: tuple[tuple[str, ...], ...]
    required_points: tuple[str, ...]
    prohibited_claims: tuple[str, ...]
    non_authoritative_evidence: tuple[str, ...]


@dataclass(frozen=True)
class HiddenVariant:
    variant_id: str
    family_id: str
    slot: int
    domain: str
    difficulty: str
    archetype: str | None
    question: str
    context_files: tuple[str, ...]
    reference: HiddenReference
    rubric: HiddenRubric


@dataclass(frozen=True)
class HiddenBank:
    schema_version: int
    dataset_version: str
    rubric_version: str
    variants: tuple[HiddenVariant, ...]


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


class _VariantPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    variant_id: str
    family_id: str
    slot: StrictInt
    domain: str
    difficulty: str
    archetype: str | None = None
    question: str
    context_files: tuple[str, str]
    reference: _ReferencePayload
    rubric: _RubricPayload

    @field_validator(
        "variant_id", "family_id", "domain", "difficulty", "question", mode="after"
    )
    @classmethod
    def validate_non_empty_string(cls, value: str) -> str:
        if not value:
            raise ValueError("Hidden variant string fields must be non-empty.")
        return value

    @field_validator("archetype")
    @classmethod
    def validate_archetype(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value:
            raise ValueError("Hidden variant archetype must be a non-empty string.")
        return value

    @field_validator("slot")
    @classmethod
    def validate_slot(cls, value: int) -> int:
        if value < 1 or value > EXPECTED_VARIANTS_PER_FAMILY:
            raise ValueError("Hidden variant slot must be between 1 and 8.")
        return value

    @field_validator("context_files")
    @classmethod
    def validate_context_files(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != 2:
            raise ValueError("Hidden variants must list exactly two context files.")
        if len(set(values)) != len(values):
            raise ValueError("Hidden variants must use distinct context files.")
        if any(not value for value in values):
            raise ValueError("Hidden variant context files must be non-empty.")
        return values


class _BankPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: StrictInt
    dataset_version: str
    rubric_version: str
    variants: tuple[_VariantPayload, ...]

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: int) -> int:
        if value != EXPECTED_SCHEMA_VERSION:
            raise ValueError("Hidden bank schema_version must be 1.")
        return value

    @field_validator("dataset_version", "rubric_version")
    @classmethod
    def validate_version_string(cls, value: str) -> str:
        if not value:
            raise ValueError("Hidden bank version fields must be non-empty strings.")
        return value

    @field_validator("variants")
    @classmethod
    def validate_variants_non_empty(
        cls, values: tuple[_VariantPayload, ...]
    ) -> tuple[_VariantPayload, ...]:
        if not values:
            raise ValueError("Hidden bank variants must not be empty.")
        return values


def load_hidden_bank(
    path: Path, public_directory: Path = PUBLIC_DIRECTORY
) -> HiddenBank:
    try:
        raw_payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Hidden bank not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Hidden bank is invalid JSON: {path}") from exc
    return _parse_hidden_bank(raw_payload, public_directory=public_directory)


def build_hidden_bank(
    input_directory: Path,
    output_path: Path,
    public_directory: Path = PUBLIC_DIRECTORY,
    repository_root: Path | None = None,
) -> HiddenBank:
    input_paths = sorted(input_directory.glob("*.json"))
    if not input_paths:
        raise ValueError(
            f"Hidden bank input directory has no JSON files: {input_directory}"
        )

    payloads = [_read_bank_payload(path) for path in input_paths]
    first_payload = payloads[0]
    for payload in payloads[1:]:
        if payload.schema_version != first_payload.schema_version:
            raise ValueError(
                "All hidden bank domain files must share one schema version."
            )
        if payload.dataset_version != first_payload.dataset_version:
            raise ValueError(
                "All hidden bank domain files must share one dataset version."
            )
        if payload.rubric_version != first_payload.rubric_version:
            raise ValueError(
                "All hidden bank domain files must share one rubric version."
            )

    combined_payload = {
        "schema_version": first_payload.schema_version,
        "dataset_version": first_payload.dataset_version,
        "rubric_version": first_payload.rubric_version,
        "variants": [
            variant.model_dump(mode="python")
            for payload in payloads
            for variant in payload.variants
        ],
    }
    bank = _parse_hidden_bank(combined_payload, public_directory=public_directory)
    _validate_output_path(output_path=output_path, repository_root=repository_root)
    _write_hidden_bank(output_path, bank)
    return bank


def assign_hidden_variant(
    bank: HiddenBank, *, team_id: str, family_id: str, attempt: int
) -> HiddenVariant:
    if not team_id.strip():
        raise ValueError("Team ID must be a non-empty string.")
    if attempt < 1 or attempt > EXPECTED_VARIANTS_PER_FAMILY:
        raise ValueError("Attempt must be between 1 and 8.")

    variants_by_family = _variants_by_family(bank)
    family_variants = variants_by_family.get(family_id)
    if family_variants is None:
        raise ValueError(f"Unknown hidden family ID: {family_id}")

    offset = _stable_offset(team_id=team_id, family_id=family_id)
    slot = ((offset + attempt - 1) % EXPECTED_VARIANTS_PER_FAMILY) + 1
    return family_variants[slot]


def build_attempt_suite(
    bank: HiddenBank, *, team_id: str, attempt: int
) -> tuple[HiddenVariant, ...]:
    variants_by_family = _variants_by_family(bank)
    suite = tuple(
        assign_hidden_variant(
            bank,
            team_id=team_id,
            family_id=family_id,
            attempt=attempt,
        )
        for family_id in sorted(variants_by_family)
    )
    difficulty_counts = Counter(variant.difficulty for variant in suite)
    if dict(difficulty_counts) != DIFFICULTY_COUNTS:
        raise ValueError(
            "Hidden suite assignment must preserve the 10/30/10 difficulty mix."
        )
    return suite


def _read_bank_payload(path: Path) -> _BankPayload:
    try:
        raw_payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Hidden bank domain file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Hidden bank domain file is invalid JSON: {path}") from exc

    try:
        return _BankPayload.model_validate(raw_payload)
    except ValidationError as exc:
        messages = "; ".join(error["msg"] for error in exc.errors())
        raise ValueError(
            f"Hidden bank domain file failed schema validation: {messages}"
        ) from exc


def _parse_hidden_bank(raw_payload: object, public_directory: Path) -> HiddenBank:
    try:
        payload = _BankPayload.model_validate(raw_payload)
    except ValidationError as exc:
        raise ValueError("Hidden bank failed schema validation.") from exc

    variants = tuple(
        sorted(
            (_build_variant(variant) for variant in payload.variants),
            key=lambda variant: (variant.family_id, variant.slot),
        )
    )
    bank = HiddenBank(
        schema_version=payload.schema_version,
        dataset_version=payload.dataset_version,
        rubric_version=payload.rubric_version,
        variants=variants,
    )
    _validate_hidden_bank(bank, load_public_cases(public_directory))
    return bank


def _build_variant(payload: _VariantPayload) -> HiddenVariant:
    return HiddenVariant(
        variant_id=payload.variant_id,
        family_id=payload.family_id,
        slot=payload.slot,
        domain=payload.domain,
        difficulty=payload.difficulty,
        archetype=payload.archetype,
        question=payload.question,
        context_files=payload.context_files,
        reference=HiddenReference(
            answer=payload.reference.answer,
            citations=tuple(payload.reference.citations),
            escalate=payload.reference.escalate,
            key_points=tuple(payload.reference.key_points),
        ),
        rubric=HiddenRubric(
            required_citation_groups=tuple(
                tuple(group) for group in payload.rubric.required_citation_groups
            ),
            required_points=tuple(payload.rubric.required_points),
            prohibited_claims=tuple(payload.rubric.prohibited_claims),
            non_authoritative_evidence=tuple(payload.rubric.non_authoritative_evidence),
        ),
    )


def _validate_hidden_bank(
    bank: HiddenBank, public_cases: tuple[PublicCase, ...]
) -> None:
    public_cases_by_id = {case.id: case for case in public_cases}
    if len(public_cases_by_id) != len(public_cases):
        raise ValueError(
            "Public cases must contain unique IDs before hidden validation."
        )

    if len(bank.variants) != len(public_cases) * EXPECTED_VARIANTS_PER_FAMILY:
        raise ValueError("Hidden bank must contain exactly 400 variants.")

    family_slots: dict[str, set[int]] = {}
    variants_by_id: dict[str, HiddenVariant] = {}
    normalized_questions: set[str] = set()
    family_ids = set(public_cases_by_id)
    variant_ids = {variant.variant_id for variant in bank.variants}

    if len(variant_ids) != len(bank.variants):
        raise ValueError("Hidden bank must contain unique variant IDs.")
    if family_ids & variant_ids:
        raise ValueError("Hidden variant IDs must stay disjoint from family IDs.")

    for variant in bank.variants:
        public_case = public_cases_by_id.get(variant.family_id)
        if public_case is None:
            raise ValueError(
                f"Hidden variant references unknown family ID: {variant.family_id}"
            )
        if variant.domain != public_case.domain:
            raise ValueError(
                f"Hidden variant {variant.variant_id} uses the wrong domain."
            )
        if variant.difficulty != public_case.difficulty:
            raise ValueError(
                f"Hidden variant {variant.variant_id} uses the wrong difficulty."
            )
        if set(variant.context_files) != set(public_case.context_files):
            raise ValueError(
                f"Hidden variant {variant.variant_id} includes undisclosed context."
            )

        question_key = _normalize_text(variant.question)
        if question_key in normalized_questions:
            raise ValueError("Hidden bank contains duplicate question text.")
        normalized_questions.add(question_key)

        _validate_evidence_ids(
            evidence_ids=variant.reference.citations,
            allowed_ids=public_case.evidence_ids,
            label=f"Hidden variant {variant.variant_id} reference has unknown citation IDs",
        )
        for group in variant.rubric.required_citation_groups:
            _validate_evidence_ids(
                evidence_ids=group,
                allowed_ids=public_case.evidence_ids,
                label=(
                    f"Hidden variant {variant.variant_id} rubric has unknown citation IDs"
                ),
            )
        _validate_evidence_ids(
            evidence_ids=variant.rubric.non_authoritative_evidence,
            allowed_ids=public_case.evidence_ids,
            label=(
                f"Hidden variant {variant.variant_id} rubric has unknown non-authoritative evidence IDs"
            ),
        )

        family_slots.setdefault(variant.family_id, set()).add(variant.slot)
        variants_by_id[variant.variant_id] = variant

    for family_id in sorted(public_cases_by_id):
        slots = family_slots.get(family_id)
        if slots != set(range(1, EXPECTED_VARIANTS_PER_FAMILY + 1)):
            raise ValueError(
                f"Hidden family {family_id} must define slots 1 through 8 exactly once."
            )

    sample_team_id = "validation-team"
    seen_variant_ids: set[str] = set()
    for attempt in range(1, EXPECTED_VARIANTS_PER_FAMILY + 1):
        suite = build_attempt_suite(bank, team_id=sample_team_id, attempt=attempt)
        if len(suite) != len(public_cases):
            raise ValueError(
                "Hidden suite assignment must contain 50 variants per attempt."
            )
        suite_variant_ids = {variant.variant_id for variant in suite}
        if len(suite_variant_ids) != len(public_cases):
            raise ValueError(
                "Hidden suite assignment must not repeat variants in one attempt."
            )
        if seen_variant_ids & suite_variant_ids:
            raise ValueError(
                "Hidden suite assignment must not repeat variants for a team."
            )
        seen_variant_ids.update(suite_variant_ids)


def _validate_evidence_ids(
    evidence_ids: Iterable[str], allowed_ids: frozenset[str], label: str
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


def _variants_by_family(bank: HiddenBank) -> dict[str, dict[int, HiddenVariant]]:
    variants: dict[str, dict[int, HiddenVariant]] = {}
    for variant in bank.variants:
        family_variants = variants.setdefault(variant.family_id, {})
        family_variants[variant.slot] = variant
    return variants


def _stable_offset(team_id: str, family_id: str) -> int:
    seed = f"{team_id}\0{family_id}".encode("utf-8")
    digest = hashlib.sha256(seed).digest()
    return int.from_bytes(digest[:8], "big") % EXPECTED_VARIANTS_PER_FAMILY


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def _validate_output_path(
    output_path: Path, repository_root: Path | None
) -> Path | None:
    absolute_output_path = _absolute_path(output_path)
    repository_roots = _repository_roots(absolute_output_path)

    discovered_root = next(iter(repository_roots), None)
    if discovered_root is None:
        return None

    if len(repository_roots) > 1:
        raise ValueError(
            "Refusing to write hidden bank output through a nested Git repository path."
        )

    if repository_root is not None and repository_root.resolve() != discovered_root:
        raise ValueError(
            "Caller-supplied repository_root does not match the authoritative repository root."
        )

    relative_output_path = absolute_output_path.relative_to(discovered_root)
    _assert_output_path_is_ignored(discovered_root, relative_output_path)
    return discovered_root


def _write_hidden_bank(path: Path, bank: HiddenBank) -> None:
    absolute_path = _absolute_path(path)
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _serialize_hidden_bank(bank)
    descriptor = _open_descriptor_anchored_file(absolute_path)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2))
        handle.write("\n")


def _open_descriptor_anchored_file(path: Path) -> int:
    if not SUPPORTS_NOFOLLOW:
        raise ValueError("Safe hidden bank writes require O_NOFOLLOW support.")
    if not SUPPORTS_DIR_FD:
        raise ValueError("Safe hidden bank writes require dir_fd support.")
    if not SUPPORTS_FCHMOD:
        raise ValueError("Safe hidden bank writes require fchmod support.")

    parent_directory = path.parent
    parent_directory.mkdir(parents=True, exist_ok=True)

    try:
        parent_fd = os.open(parent_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise ValueError(
            "Refusing to write hidden bank output through a non-regular parent directory."
        ) from exc

    try:
        flags = os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW
        descriptor = os.open(path.name, flags, 0o600, dir_fd=parent_fd)
    except OSError as exc:
        os.close(parent_fd)
        raise ValueError(
            "Refusing to write hidden bank output because the final path component is unsafe."
        ) from exc

    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError(
                "Refusing to write hidden bank output because the target is not a regular file."
            )
        os.fchmod(descriptor, 0o600)
    except Exception:
        os.close(descriptor)
        raise
    finally:
        os.close(parent_fd)

    return descriptor


def _serialize_hidden_bank(bank: HiddenBank) -> dict[str, object]:
    variants = sorted(
        bank.variants, key=lambda variant: (variant.family_id, variant.slot)
    )
    return {
        "schema_version": bank.schema_version,
        "dataset_version": bank.dataset_version,
        "rubric_version": bank.rubric_version,
        "variants": [
            {
                "variant_id": variant.variant_id,
                "family_id": variant.family_id,
                "slot": variant.slot,
                "domain": variant.domain,
                "difficulty": variant.difficulty,
                "archetype": variant.archetype,
                "question": variant.question,
                "context_files": list(variant.context_files),
                "reference": {
                    "answer": variant.reference.answer,
                    "citations": list(variant.reference.citations),
                    "escalate": variant.reference.escalate,
                    "key_points": list(variant.reference.key_points),
                },
                "rubric": {
                    "required_citation_groups": [
                        list(group) for group in variant.rubric.required_citation_groups
                    ],
                    "required_points": list(variant.rubric.required_points),
                    "prohibited_claims": list(variant.rubric.prohibited_claims),
                    "non_authoritative_evidence": list(
                        variant.rubric.non_authoritative_evidence
                    ),
                },
            }
            for variant in variants
        ],
    }


def _absolute_path(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


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
        raise ValueError("Unable to validate hidden bank output path against git.")
    if completed.returncode not in {0, 1}:
        raise ValueError("Unable to validate hidden bank output path against git.")

    output_lines = [line for line in completed.stdout.splitlines() if line]
    if not output_lines:
        raise ValueError("Hidden bank output path is not ignored by the repository.")

    last_line = output_lines[-1]
    prefix, _, _pathname = last_line.partition("\t")
    if not _pathname:
        raise ValueError("Hidden bank output path is not ignored by the repository.")

    source, line_number, pattern = prefix.split(":", 2)
    if source == "" and line_number == "" and pattern == "":
        raise ValueError("Hidden bank output path is not ignored by the repository.")
    if pattern.startswith("!"):
        raise ValueError(
            "Hidden bank output path is only matched by a negated ignore rule."
        )
    if completed.returncode != 0:
        raise ValueError("Hidden bank output path is not ignored by the repository.")
