from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol, cast

from .evaluation_bank import (
    ARCHETYPES,
    ARCHETYPE_PARTITION_COUNTS,
    PARTITION_COUNTS,
    EvaluationBank,
    EvaluationCase,
)
from .fireworks import (
    FIREWORKS_MODEL,
    JUDGE_TIERS,
    JUDGE_MODEL,
    CompletionClient,
    validate_scoring_models,
)
from .scoring import MAX_RUN_TOKENS, score_prompt


TARGET_RUN_TOKENS = 850_000
PROFILE_SPECS = (
    ("output_contract", "attempt-01.txt"),
    ("evidence_authority", "attempt-02.txt"),
    ("conflict_resistance", "attempt-03.txt"),
    ("uncertainty_escalation", "attempt-04.txt"),
)
AUTHORITY_CRITERIA = ("evidence_coverage", "faithfulness")
CONFLICT_ARCHETYPES = (
    "conflicting_or_stale_evidence",
    "prompt_injection_or_untrusted_evidence",
)
AMBIGUOUS_ARCHETYPE = "ambiguous_authority_or_escalation"
Criteria = tuple[tuple[str, float], ...]
TextFields = tuple[tuple[str, str], ...]
TierFields = tuple[tuple[str, int], ...]
ProgressCallback = Callable[[str, int, int], None]
JUDGE_CRITERIA = (
    "answer_relevance",
    "instruction_following",
    "faithfulness",
)
CHECKPOINT_SCHEMA_VERSION = 1
CHECKPOINT_FIELDS = {
    "schema_version",
    "profile_name",
    "attempt",
    "candidate_model",
    "judge_model",
    "prompt_sha256",
    "prompt_hashes",
    "calibration_input_sha256",
    "result",
}
CHECKPOINT_RESULT_FIELDS = {
    "model",
    "judge_model",
    "prompt_sha256",
    "discovery",
    "holdout",
    "overall_score",
    "token_usage",
    "call_count",
}
CHECKPOINT_PARTITION_FIELDS = {"case_count", "criteria", "score", "cases"}
CHECKPOINT_CASE_FIELDS = {
    "case_id",
    "criteria",
    "score",
    "output",
    "reasons",
    "judge",
}


class CalibrationScorer(Protocol):
    def __call__(
        self,
        *,
        team_id: str,
        attempt: int,
        run_id: str,
        participant_prompt: str,
        cases: tuple[EvaluationCase, ...],
        public_directory: Path,
        candidate_client: CompletionClient,
        judge_client: CompletionClient,
        candidate_model: str,
        judge_model: str,
        max_calls: int,
        max_run_tokens: int,
        include_holdout_details: bool,
        on_case_start: Callable[[int, int], None] | None = None,
        allow_experimental_candidate: bool = False,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class CalibrationProfile:
    name: str
    filename: str
    prompt: str
    prompt_sha256: str


@dataclass(frozen=True)
class PartitionAggregate:
    case_count: int
    criteria: Criteria
    score: float


@dataclass(frozen=True)
class ArchetypeAggregate:
    archetype: str
    case_count: int
    criteria: Criteria
    score: float


@dataclass(frozen=True)
class TokenBucket:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class TokenUsage:
    candidate: TokenBucket
    judge: TokenBucket
    total: TokenBucket


@dataclass(frozen=True)
class JudgeDiagnostic:
    raw_tiers: TierFields
    effective_tiers: TierFields
    required_points_met: tuple[int, ...]
    prohibited_claims_present: tuple[int, ...]
    non_authoritative_evidence_used: tuple[str, ...]
    cap_explanations: TextFields


@dataclass(frozen=True)
class CaseDiagnostic:
    case_id: str
    output: str
    criteria: Criteria
    reasons: TextFields
    judge: JudgeDiagnostic


@dataclass(frozen=True)
class CalibrationProfileResult:
    name: str
    prompt_sha256: str
    overall_score: float
    discovery: PartitionAggregate
    holdout: PartitionAggregate
    archetypes: tuple[ArchetypeAggregate, ...]
    diagnostics: tuple[CaseDiagnostic, ...]
    token_usage: TokenUsage
    call_count: int


@dataclass(frozen=True)
class CaseDelta:
    case_id: str
    partition: str
    archetype: str
    scores: Criteria
    deltas_from_previous: Criteria
    deltas_from_baseline: Criteria


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    actual: int | float
    operator: str
    threshold: int | float


@dataclass(frozen=True)
class CalibrationResult:
    schema_version: int
    candidate_model: str
    judge_model: str
    profiles: tuple[CalibrationProfileResult, ...]
    case_deltas: tuple[CaseDelta, ...]
    gates: tuple[GateResult, ...]

    @property
    def passed(self) -> bool:
        return all(gate.passed for gate in self.gates)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_model": self.candidate_model,
            "judge_model": self.judge_model,
            "profile_order": [profile.name for profile in self.profiles],
            "profiles": [_profile_to_dict(profile) for profile in self.profiles],
            "diagnostics": {
                profile.name: {
                    diagnostic.case_id: _case_diagnostic_to_dict(diagnostic)
                    for diagnostic in profile.diagnostics
                }
                for profile in self.profiles
            },
            "case_deltas": [_case_delta_to_dict(delta) for delta in self.case_deltas],
            "gates": {
                gate.name: {
                    "passed": gate.passed,
                    "actual": gate.actual,
                    "operator": gate.operator,
                    "threshold": gate.threshold,
                }
                for gate in self.gates
            },
            "passed": self.passed,
        }


@dataclass(frozen=True)
class _CaseScore:
    case: EvaluationCase
    criteria: Criteria
    score: float
    diagnostic: CaseDiagnostic


def run_calibration(
    *,
    bank: EvaluationBank,
    repository_root: Path,
    prompt_directory: Path,
    public_directory: Path,
    output_path: Path,
    candidate_client: CompletionClient,
    judge_client: CompletionClient,
    candidate_model: str = FIREWORKS_MODEL,
    judge_model: str = JUDGE_MODEL,
    allow_experimental_candidate: bool = False,
    scorer: CalibrationScorer | None = None,
    on_progress: ProgressCallback | None = None,
) -> CalibrationResult:
    prompt_directory, output_path = validate_calibration_paths(
        repository_root=repository_root,
        prompt_directory=prompt_directory,
        public_directory=public_directory,
        output_path=output_path,
    )
    candidate_model, judge_model = validate_scoring_models(
        candidate_model,
        judge_model,
        allow_experimental_candidate=allow_experimental_candidate,
    )
    _validate_bank(bank)
    profiles = _load_profiles(prompt_directory)
    score = scorer or cast(CalibrationScorer, score_prompt)
    prompt_hashes = {profile.name: profile.prompt_sha256 for profile in profiles}
    calibration_input_sha256 = _calibration_input_sha256(bank, public_directory)
    cached_profiles = _load_profile_checkpoints(
        output_path=output_path,
        profiles=profiles,
        bank=bank,
        candidate_model=candidate_model,
        judge_model=judge_model,
        prompt_hashes=prompt_hashes,
        calibration_input_sha256=calibration_input_sha256,
    )
    profile_results: list[CalibrationProfileResult] = []
    case_scores: list[dict[str, _CaseScore]] = []

    for attempt, profile in enumerate(profiles, start=1):
        cached = cached_profiles.get(profile.name)
        if cached is not None:
            profile_result, profile_case_scores = cached
            profile_results.append(profile_result)
            case_scores.append(profile_case_scores)
            continue
        case_callback = _case_callback(profile.name, on_progress)
        score_args = {
            "team_id": "organizer-calibration",
            "attempt": attempt,
            "run_id": f"calibration-{profile.name}",
            "participant_prompt": profile.prompt,
            "cases": bank.cases,
            "public_directory": public_directory,
            "candidate_client": candidate_client,
            "judge_client": judge_client,
            "candidate_model": candidate_model,
            "judge_model": judge_model,
            "max_calls": 100,
            "max_run_tokens": MAX_RUN_TOKENS,
            "include_holdout_details": True,
            "on_case_start": case_callback,
        }
        if allow_experimental_candidate:
            score_args["allow_experimental_candidate"] = True
        raw_result = score(**score_args)
        profile_result, profile_case_scores = _parse_profile_result(
            profile=profile,
            raw_result=raw_result,
            bank=bank,
            candidate_model=candidate_model,
            judge_model=judge_model,
        )
        checkpoint_path = _checkpoint_path(output_path, attempt, profile)
        _write_private_json(
            checkpoint_path,
            _checkpoint_payload(
                attempt=attempt,
                profile=profile,
                profiles=profiles,
                profile_result=profile_result,
                profile_case_scores=profile_case_scores,
                candidate_model=candidate_model,
                judge_model=judge_model,
                calibration_input_sha256=calibration_input_sha256,
            ),
        )
        profile_results.append(profile_result)
        case_scores.append(profile_case_scores)

    results = tuple(profile_results)
    result = CalibrationResult(
        schema_version=1,
        candidate_model=candidate_model,
        judge_model=judge_model,
        profiles=results,
        case_deltas=_build_case_deltas(bank, profiles, case_scores),
        gates=_build_gates(results, case_scores),
    )
    _write_private_json(output_path, result.to_dict())
    return result


def _validate_bank(bank: EvaluationBank) -> None:
    if len(bank.cases) != 50:
        raise ValueError("Calibration requires exactly 50 evaluation cases.")
    case_ids = [case.case_id for case in bank.cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Calibration evaluation case IDs must be unique.")
    if dict(Counter(case.partition for case in bank.cases)) != PARTITION_COUNTS:
        raise ValueError(
            "Calibration requires exactly 40 discovery and 10 holdout cases."
        )
    archetype_partitions = {
        partition: dict(
            Counter(
                case.archetype for case in bank.cases if case.partition == partition
            )
        )
        for partition in PARTITION_COUNTS
    }
    if archetype_partitions != ARCHETYPE_PARTITION_COUNTS:
        raise ValueError(
            "Calibration requires exactly 8 discovery and 2 holdout cases for each archetype."
        )


def validate_calibration_paths(
    *,
    repository_root: Path,
    prompt_directory: Path,
    public_directory: Path,
    output_path: Path,
) -> tuple[Path, Path]:
    root = repository_root.resolve()
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or Path(completed.stdout.strip()).resolve() != root:
        raise ValueError(
            "Calibration repository root must be the Git repository top level."
        )

    local_root = root / ".local"
    prompt_root = _absolute_path(prompt_directory).resolve()
    output = _absolute_path(output_path).resolve()
    for label, path in (("prompt directory", prompt_root), ("output", output)):
        if path == local_root or not path.is_relative_to(local_root):
            raise ValueError(
                "Calibration prompt directory and output must be under the "
                "repository .local tree."
            )
        relative_path = path.relative_to(root)
        _assert_path_is_untracked(root, relative_path, label)
        _assert_path_is_ignored(root, relative_path, label)

    _validate_output_path(output, public_directory, prompt_root)
    checkpoint_root = _checkpoint_directory(output)
    relative_checkpoint_root = checkpoint_root.relative_to(root)
    _assert_path_is_untracked(root, relative_checkpoint_root, "checkpoint directory")
    _assert_path_is_ignored(root, relative_checkpoint_root, "checkpoint directory")
    return prompt_root, output


def _absolute_path(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def _assert_path_is_untracked(
    repository_root: Path,
    relative_path: Path,
    label: str,
) -> None:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repository_root),
            "ls-files",
            "--",
            str(relative_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ValueError("Unable to validate calibration paths against Git tracking.")
    if completed.stdout.strip():
        raise ValueError(f"Calibration {label} path is tracked by Git.")


def _assert_path_is_ignored(
    repository_root: Path,
    relative_path: Path,
    label: str,
) -> None:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repository_root),
            "check-ignore",
            "-q",
            "--",
            str(relative_path),
        ],
        check=False,
    )
    if completed.returncode == 1:
        raise ValueError(f"Calibration {label} path is not ignored by Git.")
    if completed.returncode != 0:
        raise ValueError("Unable to validate calibration paths with git check-ignore.")


def _validate_output_path(
    output_path: Path,
    public_directory: Path,
    prompt_directory: Path,
) -> None:
    output = output_path.resolve()
    public_root = public_directory.resolve()
    if output == public_root or output.is_relative_to(public_root):
        raise ValueError("Calibration output must remain outside the public directory.")
    prompt_root = prompt_directory.resolve()
    if output == prompt_root or output.is_relative_to(prompt_root):
        raise ValueError("Calibration output must remain outside the prompt directory.")


def _load_profiles(prompt_directory: Path) -> tuple[CalibrationProfile, ...]:
    if not prompt_directory.is_dir():
        raise ValueError("Calibration prompt directory does not exist.")
    expected_filenames = tuple(filename for _, filename in PROFILE_SPECS)
    actual_filenames = tuple(sorted(path.name for path in prompt_directory.iterdir()))
    if actual_filenames != expected_filenames:
        raise ValueError(
            "Calibration prompt directory must contain exactly four files: "
            + ", ".join(expected_filenames)
            + "."
        )

    profiles: list[CalibrationProfile] = []
    for name, filename in PROFILE_SPECS:
        path = prompt_directory / filename
        if not path.is_file():
            raise ValueError(f"Calibration prompt is not a file: {filename}.")
        prompt = path.read_text(encoding="utf-8").strip()
        if not prompt:
            raise ValueError(f"Calibration prompt must not be empty: {filename}.")
        profiles.append(
            CalibrationProfile(
                name=name,
                filename=filename,
                prompt=prompt,
                prompt_sha256=sha256(prompt.encode("utf-8")).hexdigest(),
            )
        )

    for previous, current in zip(profiles, profiles[1:]):
        suffix = current.prompt[len(previous.prompt) :]
        if (
            not current.prompt.startswith(previous.prompt)
            or not suffix.startswith("\n\n")
            or not suffix.strip()
        ):
            raise ValueError(
                f"Calibration prompts must be cumulative: {current.filename} must "
                f"retain all of {previous.filename} before its strategy block."
            )
    return tuple(profiles)


def _checkpoint_directory(output_path: Path) -> Path:
    return output_path.parent / f".{output_path.name}.checkpoints"


def _checkpoint_path(
    output_path: Path,
    attempt: int,
    profile: CalibrationProfile,
) -> Path:
    return _checkpoint_directory(output_path) / f"{attempt:02d}-{profile.name}.json"


def _calibration_input_sha256(
    bank: EvaluationBank,
    public_directory: Path,
) -> str:
    context_hashes: dict[str, str | None] = {}
    for relative_path in sorted(
        {path for case in bank.cases for path in case.context_files}
    ):
        path = public_directory / relative_path
        context_hashes[relative_path] = (
            sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        )
    canonical = json.dumps(
        {"bank": asdict(bank), "public_context_sha256": context_hashes},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def _load_profile_checkpoints(
    *,
    output_path: Path,
    profiles: tuple[CalibrationProfile, ...],
    bank: EvaluationBank,
    candidate_model: str,
    judge_model: str,
    prompt_hashes: Mapping[str, str],
    calibration_input_sha256: str,
) -> dict[str, tuple[CalibrationProfileResult, dict[str, _CaseScore]]]:
    checkpoint_directory = _checkpoint_directory(output_path)
    expected_paths = {
        _checkpoint_path(output_path, attempt, profile).name: (attempt, profile)
        for attempt, profile in enumerate(profiles, start=1)
    }
    if not checkpoint_directory.exists():
        return {}
    directory_stat = checkpoint_directory.lstat()
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise ValueError("Calibration checkpoint path must be a directory.")
    actual_paths = {path.name: path for path in checkpoint_directory.iterdir()}
    unexpected = sorted(set(actual_paths) - set(expected_paths))
    if unexpected:
        raise ValueError(
            "Calibration checkpoint directory contains unexpected files: "
            + ", ".join(unexpected)
            + "."
        )

    cached: dict[str, tuple[CalibrationProfileResult, dict[str, _CaseScore]]] = {}
    for filename, (attempt, profile) in expected_paths.items():
        path = actual_paths.get(filename)
        if path is None:
            continue
        cached[profile.name] = _load_profile_checkpoint(
            path=path,
            attempt=attempt,
            profile=profile,
            profiles=profiles,
            bank=bank,
            candidate_model=candidate_model,
            judge_model=judge_model,
            prompt_hashes=prompt_hashes,
            calibration_input_sha256=calibration_input_sha256,
        )
    return cached


def _load_profile_checkpoint(
    *,
    path: Path,
    attempt: int,
    profile: CalibrationProfile,
    profiles: tuple[CalibrationProfile, ...],
    bank: EvaluationBank,
    candidate_model: str,
    judge_model: str,
    prompt_hashes: Mapping[str, str],
    calibration_input_sha256: str,
) -> tuple[CalibrationProfileResult, dict[str, _CaseScore]]:
    file_stat = path.lstat()
    if not stat.S_ISREG(file_stat.st_mode):
        raise ValueError(f"Calibration checkpoint is not a regular file: {path.name}.")
    if stat.S_IMODE(file_stat.st_mode) != 0o600:
        raise ValueError(f"Calibration checkpoint must use mode 0600: {path.name}.")
    try:
        raw_payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Calibration checkpoint is invalid: {path.name}.") from exc
    if not isinstance(raw_payload, dict):
        raise ValueError(f"Calibration checkpoint must be an object: {path.name}.")
    payload = cast(dict[str, object], raw_payload)
    if set(payload) != CHECKPOINT_FIELDS:
        raise ValueError(f"Calibration checkpoint fields are invalid: {path.name}.")
    if _required_int(payload, "schema_version") != CHECKPOINT_SCHEMA_VERSION:
        raise ValueError(f"Calibration checkpoint schema is stale: {path.name}.")
    if _required_string(payload, "profile_name") != profile.name:
        raise ValueError(f"Calibration checkpoint profile is stale: {path.name}.")
    if _required_int(payload, "attempt") != attempt:
        raise ValueError(f"Calibration checkpoint attempt is stale: {path.name}.")
    if _required_string(payload, "candidate_model") != candidate_model:
        raise ValueError(
            f"Calibration checkpoint candidate model is stale: {path.name}."
        )
    if _required_string(payload, "judge_model") != judge_model:
        raise ValueError(f"Calibration checkpoint judge model is stale: {path.name}.")
    if _required_string(payload, "prompt_sha256") != profile.prompt_sha256:
        raise ValueError(f"Calibration checkpoint prompt hash is stale: {path.name}.")
    _validate_checkpoint_prompt_hashes(
        payload,
        profiles=profiles,
        expected=prompt_hashes,
        path=path,
    )
    if (
        _required_string(payload, "calibration_input_sha256")
        != calibration_input_sha256
    ):
        raise ValueError(f"Calibration checkpoint inputs are stale: {path.name}.")
    raw_result = _required_mapping(payload, "result")
    try:
        _validate_checkpoint_result_shape(raw_result)
        return _parse_profile_result(
            profile=profile,
            raw_result=raw_result,
            bank=bank,
            candidate_model=candidate_model,
            judge_model=judge_model,
        )
    except ValueError as exc:
        raise ValueError(
            f"Calibration checkpoint result is invalid: {path.name}: {exc}"
        ) from exc


def _validate_checkpoint_prompt_hashes(
    payload: Mapping[str, object],
    *,
    profiles: tuple[CalibrationProfile, ...],
    expected: Mapping[str, str],
    path: Path,
) -> None:
    raw_hashes = _required_mapping(payload, "prompt_hashes")
    if set(raw_hashes) != {profile.name for profile in profiles}:
        raise ValueError(
            f"Calibration checkpoint prompt hashes are stale: {path.name}."
        )
    actual = {name: _required_string(raw_hashes, name) for name in raw_hashes}
    if actual != dict(expected):
        raise ValueError(
            f"Calibration checkpoint prompt hashes are stale: {path.name}."
        )


def _validate_checkpoint_result_shape(raw_result: Mapping[str, object]) -> None:
    if set(raw_result) != CHECKPOINT_RESULT_FIELDS:
        raise ValueError("checkpoint result fields are incomplete")
    for partition in PARTITION_COUNTS:
        raw_partition = _required_mapping(raw_result, partition)
        if set(raw_partition) != CHECKPOINT_PARTITION_FIELDS:
            raise ValueError(f"checkpoint {partition} fields are incomplete")
        raw_cases = raw_partition.get("cases")
        if not isinstance(raw_cases, list):
            raise ValueError(f"checkpoint {partition} cases must be an array")
        for raw_case in cast(list[object], raw_cases):
            if not isinstance(raw_case, dict):
                raise ValueError("checkpoint case fields are incomplete")
            case_mapping = cast(dict[str, object], raw_case)
            if set(case_mapping) != CHECKPOINT_CASE_FIELDS:
                raise ValueError("checkpoint case fields are incomplete")
    raw_usage = _required_mapping(raw_result, "token_usage")
    if set(raw_usage) != {"candidate", "judge", "total"}:
        raise ValueError("checkpoint token usage fields are incomplete")
    for bucket_name in ("candidate", "judge", "total"):
        bucket = _required_mapping(raw_usage, bucket_name)
        if set(bucket) != {"prompt_tokens", "completion_tokens", "total_tokens"}:
            raise ValueError("checkpoint token bucket fields are incomplete")


def _checkpoint_payload(
    *,
    attempt: int,
    profile: CalibrationProfile,
    profiles: tuple[CalibrationProfile, ...],
    profile_result: CalibrationProfileResult,
    profile_case_scores: Mapping[str, _CaseScore],
    candidate_model: str,
    judge_model: str,
    calibration_input_sha256: str,
) -> dict[str, object]:
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "profile_name": profile.name,
        "attempt": attempt,
        "candidate_model": candidate_model,
        "judge_model": judge_model,
        "prompt_sha256": profile.prompt_sha256,
        "prompt_hashes": {item.name: item.prompt_sha256 for item in profiles},
        "calibration_input_sha256": calibration_input_sha256,
        "result": _checkpoint_result(
            profile_result,
            profile_case_scores,
            candidate_model=candidate_model,
            judge_model=judge_model,
        ),
    }


def _checkpoint_result(
    profile_result: CalibrationProfileResult,
    profile_case_scores: Mapping[str, _CaseScore],
    *,
    candidate_model: str,
    judge_model: str,
) -> dict[str, object]:
    return {
        "model": candidate_model,
        "judge_model": judge_model,
        "prompt_sha256": profile_result.prompt_sha256,
        "discovery": _checkpoint_partition(
            profile_result.discovery,
            profile_case_scores,
            "discovery",
        ),
        "holdout": _checkpoint_partition(
            profile_result.holdout,
            profile_case_scores,
            "holdout",
        ),
        "overall_score": profile_result.overall_score,
        "token_usage": _token_usage_to_dict(profile_result.token_usage),
        "call_count": profile_result.call_count,
    }


def _checkpoint_partition(
    aggregate: PartitionAggregate,
    profile_case_scores: Mapping[str, _CaseScore],
    partition: str,
) -> dict[str, object]:
    payload = _partition_to_dict(aggregate)
    payload["cases"] = [
        _checkpoint_case(item)
        for item in profile_case_scores.values()
        if item.case.partition == partition
    ]
    return payload


def _checkpoint_case(item: _CaseScore) -> dict[str, object]:
    diagnostic = _case_diagnostic_to_dict(item.diagnostic)
    return {
        "case_id": item.case.case_id,
        "criteria": diagnostic["criteria"],
        "score": item.score,
        "output": diagnostic["output"],
        "reasons": diagnostic["reasons"],
        "judge": diagnostic["judge"],
    }


def _case_callback(
    profile_name: str,
    on_progress: ProgressCallback | None,
) -> Callable[[int, int], None] | None:
    if on_progress is None:
        return None

    def report(current: int, total: int) -> None:
        on_progress(profile_name, current, total)

    return report


def _parse_profile_result(
    *,
    profile: CalibrationProfile,
    raw_result: Mapping[str, Any],
    bank: EvaluationBank,
    candidate_model: str,
    judge_model: str,
) -> tuple[CalibrationProfileResult, dict[str, _CaseScore]]:
    if _required_string(raw_result, "model") != candidate_model:
        raise ValueError("Calibration scorer returned the wrong candidate model.")
    if _required_string(raw_result, "judge_model") != judge_model:
        raise ValueError("Calibration scorer returned the wrong judge model.")
    if _required_string(raw_result, "prompt_sha256") != profile.prompt_sha256:
        raise ValueError("Calibration scorer returned the wrong prompt hash.")
    call_count = _required_int(raw_result, "call_count")
    if call_count != 100:
        raise ValueError("Each calibration profile must make exactly 100 model calls.")

    cases_by_partition = {
        partition: tuple(case for case in bank.cases if case.partition == partition)
        for partition in PARTITION_COUNTS
    }
    discovery, discovery_scores = _parse_partition(
        raw_result,
        "discovery",
        cases_by_partition["discovery"],
    )
    holdout, holdout_scores = _parse_partition(
        raw_result,
        "holdout",
        cases_by_partition["holdout"],
    )
    all_case_scores = {**discovery_scores, **holdout_scores}
    if len(all_case_scores) != 50:
        raise ValueError("Calibration scorer must return detail for all 50 cases.")

    overall_score = _required_number(raw_result, "overall_score")
    expected_overall = round(discovery.score * 0.75 + holdout.score * 0.25, 2)
    if overall_score != expected_overall:
        raise ValueError(
            "Calibration overall score does not match partition aggregates."
        )
    return (
        CalibrationProfileResult(
            name=profile.name,
            prompt_sha256=profile.prompt_sha256,
            overall_score=overall_score,
            discovery=discovery,
            holdout=holdout,
            archetypes=_aggregate_archetypes(all_case_scores),
            diagnostics=tuple(
                all_case_scores[case.case_id].diagnostic for case in bank.cases
            ),
            token_usage=_parse_token_usage(raw_result),
            call_count=call_count,
        ),
        all_case_scores,
    )


def _parse_partition(
    raw_result: Mapping[str, Any],
    partition: str,
    expected_cases: tuple[EvaluationCase, ...],
) -> tuple[PartitionAggregate, dict[str, _CaseScore]]:
    raw_partition = _required_mapping(raw_result, partition)
    expected_count = len(expected_cases)
    if _required_int(raw_partition, "case_count") != expected_count:
        raise ValueError(
            f"Calibration {partition} aggregate must contain {expected_count} cases."
        )
    raw_cases = raw_partition.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError(
            f"Calibration scorer must include private {partition} case detail."
        )
    raw_case_values = cast(list[object], raw_cases)
    if len(raw_case_values) != expected_count:
        raise ValueError(
            f"Calibration scorer must include all {expected_count} {partition} cases."
        )

    expected_by_id = {case.case_id: case for case in expected_cases}
    scores: dict[str, _CaseScore] = {}
    for value in raw_case_values:
        if not isinstance(value, dict):
            raise ValueError("Calibration case detail must contain JSON objects.")
        raw_case = cast(dict[str, object], value)
        case_id = _required_string(raw_case, "case_id")
        case = expected_by_id.get(case_id)
        if case is None:
            raise ValueError(
                f"Calibration {partition} detail contains unexpected case {case_id}."
            )
        if case_id in scores:
            raise ValueError(f"Calibration case detail repeats case {case_id}.")
        criteria = _parse_criteria(raw_case)
        score = _required_number(raw_case, "score")
        if score != round(sum(value for _, value in criteria), 2):
            raise ValueError(
                f"Calibration case {case_id} score must equal the rounded sum of "
                "its criteria."
            )
        diagnostic = _parse_case_diagnostic(
            raw_case,
            case=case,
            criteria=criteria,
        )
        scores[case_id] = _CaseScore(
            case=case,
            criteria=criteria,
            score=score,
            diagnostic=diagnostic,
        )
    if set(scores) != set(expected_by_id):
        raise ValueError(f"Calibration {partition} case detail is incomplete.")

    aggregate = PartitionAggregate(
        case_count=expected_count,
        criteria=_parse_criteria(raw_partition),
        score=_required_number(raw_partition, "score"),
    )
    _validate_aggregate(aggregate, tuple(scores.values()), partition)
    return aggregate, scores


def _parse_criteria(value: Mapping[str, object]) -> Criteria:
    raw_criteria = _required_mapping(value, "criteria")
    if not raw_criteria:
        raise ValueError("Calibration criteria must not be empty.")
    return tuple(
        (name, _required_number(raw_criteria, name)) for name in sorted(raw_criteria)
    )


def _parse_case_diagnostic(
    raw_case: Mapping[str, object],
    *,
    case: EvaluationCase,
    criteria: Criteria,
) -> CaseDiagnostic:
    reasons = _parse_text_fields(raw_case, "reasons", JUDGE_CRITERIA)
    return CaseDiagnostic(
        case_id=case.case_id,
        output=_required_text(raw_case, "output"),
        criteria=criteria,
        reasons=reasons,
        judge=_parse_judge_diagnostic(
            raw_case,
            case=case,
            reasons=dict(reasons),
        ),
    )


def _parse_judge_diagnostic(
    raw_case: Mapping[str, object],
    *,
    case: EvaluationCase,
    reasons: Mapping[str, str],
) -> JudgeDiagnostic:
    raw_judge = _required_mapping(raw_case, "judge")
    expected_judge_fields = {
        "raw_tiers",
        "effective_tiers",
        "audit",
        "cap_explanations",
    }
    if set(raw_judge) != expected_judge_fields:
        raise ValueError("Calibration judge diagnostic fields are incomplete.")

    raw_tiers = _parse_tier_fields(raw_judge, "raw_tiers")
    effective_tiers = _parse_tier_fields(raw_judge, "effective_tiers")
    raw_tier_map = dict(raw_tiers)
    effective_tier_map = dict(effective_tiers)
    if any(effective_tier_map[name] > raw_tier_map[name] for name in JUDGE_CRITERIA):
        raise ValueError("Calibration effective judge tiers cannot exceed raw tiers.")

    audit = _required_mapping(raw_judge, "audit")
    expected_audit_fields = {
        "required_points_met",
        "prohibited_claims_present",
        "non_authoritative_evidence_used",
    }
    if set(audit) != expected_audit_fields:
        raise ValueError("Calibration judge audit fields are incomplete.")
    required_points_met = _parse_audit_indexes(
        audit,
        "required_points_met",
        upper_bound=len(case.rubric.required_points),
    )
    prohibited_claims_present = _parse_audit_indexes(
        audit,
        "prohibited_claims_present",
        upper_bound=len(case.rubric.prohibited_claims),
    )
    non_authoritative_evidence_used = _parse_audit_evidence(
        audit,
        allowed=frozenset(case.rubric.non_authoritative_evidence),
    )

    raw_explanations = _required_mapping(raw_judge, "cap_explanations")
    capped_criteria = tuple(
        name for name in JUDGE_CRITERIA if effective_tier_map[name] < raw_tier_map[name]
    )
    if set(raw_explanations) != set(capped_criteria):
        raise ValueError(
            "Calibration cap explanations must match every reduced judge tier."
        )
    cap_explanations = _parse_text_fields(
        raw_judge,
        "cap_explanations",
        capped_criteria,
    )
    if any(reasons[name] != explanation for name, explanation in cap_explanations):
        raise ValueError(
            "Calibration capped judge reasons must match their cap explanations."
        )
    return JudgeDiagnostic(
        raw_tiers=raw_tiers,
        effective_tiers=effective_tiers,
        required_points_met=required_points_met,
        prohibited_claims_present=prohibited_claims_present,
        non_authoritative_evidence_used=non_authoritative_evidence_used,
        cap_explanations=cap_explanations,
    )


def _parse_tier_fields(value: Mapping[str, object], key: str) -> TierFields:
    raw_tiers = _required_mapping(value, key)
    if set(raw_tiers) != set(JUDGE_CRITERIA):
        raise ValueError("Calibration judge tier fields are incomplete.")
    tiers = tuple((name, _required_int(raw_tiers, name)) for name in JUDGE_CRITERIA)
    if any(tier not in JUDGE_TIERS for _, tier in tiers):
        raise ValueError(f"Calibration judge tiers must be one of {JUDGE_TIERS}.")
    return tiers


def _parse_text_fields(
    value: Mapping[str, object],
    key: str,
    field_names: tuple[str, ...],
) -> TextFields:
    raw_fields = _required_mapping(value, key)
    if set(raw_fields) != set(field_names):
        raise ValueError(f"Calibration {key} fields are incomplete.")
    return tuple((name, _required_string(raw_fields, name)) for name in field_names)


def _parse_audit_indexes(
    audit: Mapping[str, object],
    key: str,
    *,
    upper_bound: int,
) -> tuple[int, ...]:
    raw_values = audit.get(key)
    if not isinstance(raw_values, list):
        raise ValueError(f"Calibration judge audit field {key} must be an array.")
    values: list[int] = []
    for value in cast(list[object], raw_values):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"Calibration judge audit field {key} must use integers.")
        values.append(value)
    if len(values) != len(set(values)) or any(
        value < 0 or value >= upper_bound for value in values
    ):
        raise ValueError(f"Calibration judge audit field {key} is invalid.")
    return tuple(values)


def _parse_audit_evidence(
    audit: Mapping[str, object],
    *,
    allowed: frozenset[str],
) -> tuple[str, ...]:
    key = "non_authoritative_evidence_used"
    raw_values = audit.get(key)
    if not isinstance(raw_values, list):
        raise ValueError(f"Calibration judge audit field {key} must be an array.")
    values: list[str] = []
    for value in cast(list[object], raw_values):
        if not isinstance(value, str) or not value:
            raise ValueError(f"Calibration judge audit field {key} must use strings.")
        values.append(value)
    if len(values) != len(set(values)) or not set(values).issubset(allowed):
        raise ValueError(f"Calibration judge audit field {key} is invalid.")
    return tuple(values)


def _validate_aggregate(
    aggregate: PartitionAggregate,
    case_scores: tuple[_CaseScore, ...],
    label: str,
) -> None:
    computed = _aggregate_case_scores(case_scores)
    if aggregate.criteria != computed.criteria or aggregate.score != computed.score:
        raise ValueError(
            f"Calibration {label} aggregate does not match its private case detail."
        )


def _aggregate_case_scores(
    case_scores: tuple[_CaseScore, ...],
) -> PartitionAggregate:
    if not case_scores:
        raise ValueError("Calibration cannot aggregate an empty case set.")
    criterion_names = tuple(name for name, _ in case_scores[0].criteria)
    if any(
        tuple(name for name, _ in item.criteria) != criterion_names
        for item in case_scores[1:]
    ):
        raise ValueError("Calibration cases must report the same criteria.")
    criteria = tuple(
        (
            name,
            round(
                sum(dict(item.criteria)[name] for item in case_scores)
                / len(case_scores),
                2,
            ),
        )
        for name in criterion_names
    )
    return PartitionAggregate(
        case_count=len(case_scores),
        criteria=criteria,
        score=round(sum(value for _, value in criteria), 2),
    )


def _aggregate_archetypes(
    case_scores: Mapping[str, _CaseScore],
) -> tuple[ArchetypeAggregate, ...]:
    aggregates: list[ArchetypeAggregate] = []
    for archetype in ARCHETYPES:
        selected = tuple(
            item for item in case_scores.values() if item.case.archetype == archetype
        )
        aggregate = _aggregate_case_scores(selected)
        if aggregate.case_count != 10:
            raise ValueError(
                f"Calibration archetype {archetype} must contain exactly 10 cases."
            )
        aggregates.append(
            ArchetypeAggregate(
                archetype=archetype,
                case_count=aggregate.case_count,
                criteria=aggregate.criteria,
                score=aggregate.score,
            )
        )
    return tuple(aggregates)


def _parse_token_usage(raw_result: Mapping[str, Any]) -> TokenUsage:
    raw_usage = _required_mapping(raw_result, "token_usage")
    usage = TokenUsage(
        candidate=_parse_token_bucket(raw_usage, "candidate"),
        judge=_parse_token_bucket(raw_usage, "judge"),
        total=_parse_token_bucket(raw_usage, "total"),
    )
    if (
        usage.candidate.prompt_tokens + usage.judge.prompt_tokens
        != usage.total.prompt_tokens
        or usage.candidate.completion_tokens + usage.judge.completion_tokens
        != usage.total.completion_tokens
        or usage.candidate.total_tokens + usage.judge.total_tokens
        != usage.total.total_tokens
    ):
        raise ValueError("Calibration token buckets do not add up to total usage.")
    return usage


def _parse_token_bucket(
    raw_usage: Mapping[str, object],
    name: str,
) -> TokenBucket:
    value = _required_mapping(raw_usage, name)
    bucket = TokenBucket(
        prompt_tokens=_required_int(value, "prompt_tokens"),
        completion_tokens=_required_int(value, "completion_tokens"),
        total_tokens=_required_int(value, "total_tokens"),
    )
    if min(bucket.prompt_tokens, bucket.completion_tokens, bucket.total_tokens) < 0:
        raise ValueError("Calibration token counts must not be negative.")
    if bucket.prompt_tokens + bucket.completion_tokens != bucket.total_tokens:
        raise ValueError(f"Calibration {name} token usage does not add up.")
    return bucket


def _build_case_deltas(
    bank: EvaluationBank,
    profiles: tuple[CalibrationProfile, ...],
    case_scores: list[dict[str, _CaseScore]],
) -> tuple[CaseDelta, ...]:
    deltas: list[CaseDelta] = []
    for case in bank.cases:
        scores = tuple(
            (profile.name, profile_scores[case.case_id].score)
            for profile, profile_scores in zip(profiles, case_scores, strict=True)
        )
        baseline = scores[0][1]
        deltas.append(
            CaseDelta(
                case_id=case.case_id,
                partition=case.partition,
                archetype=case.archetype,
                scores=scores,
                deltas_from_previous=tuple(
                    (
                        profiles[index].name,
                        round(scores[index][1] - scores[index - 1][1], 2),
                    )
                    for index in range(1, len(profiles))
                ),
                deltas_from_baseline=tuple(
                    (profiles[index].name, round(scores[index][1] - baseline, 2))
                    for index in range(1, len(profiles))
                ),
            )
        )
    return tuple(deltas)


def _build_gates(
    profiles: tuple[CalibrationProfileResult, ...],
    case_scores: list[dict[str, _CaseScore]],
) -> tuple[GateResult, ...]:
    baseline, _, _, final = profiles
    baseline_cases, authority_cases, conflict_cases, final_cases = case_scores
    max_tokens = max(profile.token_usage.total.total_tokens for profile in profiles)
    final_over_baseline = round(final.overall_score - baseline.overall_score, 2)
    authority_delta = round(
        _average_criteria(authority_cases, AUTHORITY_CRITERIA)
        - _average_criteria(baseline_cases, AUTHORITY_CRITERIA),
        2,
    )
    conflict_delta = round(
        _average_scores(conflict_cases, archetypes=CONFLICT_ARCHETYPES)
        - _average_scores(authority_cases, archetypes=CONFLICT_ARCHETYPES),
        2,
    )
    ambiguous_delta = round(
        _average_scores(final_cases, archetypes=(AMBIGUOUS_ARCHETYPE,))
        - _average_scores(conflict_cases, archetypes=(AMBIGUOUS_ARCHETYPE,)),
        2,
    )
    final_escalation = round(
        _average_criteria(
            final_cases,
            ("escalation",),
            archetypes=(AMBIGUOUS_ARCHETYPE,),
        ),
        2,
    )
    final_gap = round(abs(final.discovery.score - final.holdout.score), 2)
    return (
        _maximum_gate("hard_token_limit", max_tokens, MAX_RUN_TOKENS),
        _maximum_gate("target_token_limit", max_tokens, TARGET_RUN_TOKENS),
        _minimum_gate("final_over_baseline", final_over_baseline, 10.0),
        _minimum_gate("authority_targeted_delta", authority_delta, 2.0),
        _minimum_gate("conflict_untrusted_delta", conflict_delta, 4.0),
        _minimum_gate("ambiguous_escalation_delta", ambiguous_delta, 4.0),
        _minimum_gate("final_escalation", final_escalation, 9.0),
        _maximum_gate("final_discovery_holdout_gap", final_gap, 10.0),
    )


def _average_scores(
    case_scores: Mapping[str, _CaseScore],
    *,
    archetypes: tuple[str, ...],
) -> float:
    selected = [
        item.score for item in case_scores.values() if item.case.archetype in archetypes
    ]
    if not selected:
        raise ValueError("Calibration gate selected no cases.")
    return sum(selected) / len(selected)


def _average_criteria(
    case_scores: Mapping[str, _CaseScore],
    criteria: tuple[str, ...],
    *,
    archetypes: tuple[str, ...] = ARCHETYPES,
) -> float:
    selected = [
        item for item in case_scores.values() if item.case.archetype in archetypes
    ]
    if not selected:
        raise ValueError("Calibration gate selected no cases.")
    try:
        return sum(
            sum(dict(item.criteria)[criterion] for criterion in criteria)
            for item in selected
        ) / len(selected)
    except KeyError as exc:
        raise ValueError(
            f"Calibration scorer did not return required criterion {exc.args[0]}."
        ) from exc


def _minimum_gate(name: str, actual: float, threshold: float) -> GateResult:
    return GateResult(
        name=name,
        passed=actual >= threshold,
        actual=actual,
        operator=">=",
        threshold=threshold,
    )


def _maximum_gate(
    name: str,
    actual: int | float,
    threshold: int | float,
) -> GateResult:
    return GateResult(
        name=name,
        passed=actual <= threshold,
        actual=actual,
        operator="<=",
        threshold=threshold,
    )


def _required_mapping(
    value: Mapping[str, object],
    key: str,
) -> Mapping[str, object]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise ValueError(f"Calibration scorer field {key} must be an object.")
    return cast(dict[str, object], item)


def _required_string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"Calibration scorer field {key} must be a non-empty string.")
    return item


def _required_text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise ValueError(f"Calibration scorer field {key} must be a string.")
    return item


def _required_int(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"Calibration scorer field {key} must be an integer.")
    return item


def _required_number(value: Mapping[str, object], key: str) -> float:
    item = value.get(key)
    if not isinstance(item, (int, float)) or isinstance(item, bool):
        raise ValueError(f"Calibration scorer field {key} must be numeric.")
    return float(item)


def _profile_to_dict(profile: CalibrationProfileResult) -> dict[str, object]:
    return {
        "name": profile.name,
        "prompt_sha256": profile.prompt_sha256,
        "overall_score": profile.overall_score,
        "discovery": _partition_to_dict(profile.discovery),
        "holdout": _partition_to_dict(profile.holdout),
        "archetypes": {
            aggregate.archetype: {
                "case_count": aggregate.case_count,
                "criteria": dict(aggregate.criteria),
                "score": aggregate.score,
            }
            for aggregate in profile.archetypes
        },
        "token_usage": _token_usage_to_dict(profile.token_usage),
        "call_count": profile.call_count,
    }


def _partition_to_dict(aggregate: PartitionAggregate) -> dict[str, object]:
    return {
        "case_count": aggregate.case_count,
        "criteria": dict(aggregate.criteria),
        "score": aggregate.score,
    }


def _token_usage_to_dict(usage: TokenUsage) -> dict[str, object]:
    return {
        "candidate": _token_bucket_to_dict(usage.candidate),
        "judge": _token_bucket_to_dict(usage.judge),
        "total": _token_bucket_to_dict(usage.total),
    }


def _token_bucket_to_dict(bucket: TokenBucket) -> dict[str, int]:
    return {
        "prompt_tokens": bucket.prompt_tokens,
        "completion_tokens": bucket.completion_tokens,
        "total_tokens": bucket.total_tokens,
    }


def _case_diagnostic_to_dict(diagnostic: CaseDiagnostic) -> dict[str, object]:
    judge = diagnostic.judge
    return {
        "output": diagnostic.output,
        "criteria": dict(diagnostic.criteria),
        "reasons": dict(diagnostic.reasons),
        "judge": {
            "raw_tiers": dict(judge.raw_tiers),
            "effective_tiers": dict(judge.effective_tiers),
            "audit": {
                "required_points_met": list(judge.required_points_met),
                "prohibited_claims_present": list(judge.prohibited_claims_present),
                "non_authoritative_evidence_used": list(
                    judge.non_authoritative_evidence_used
                ),
            },
            "cap_explanations": dict(judge.cap_explanations),
        },
    }


def _case_delta_to_dict(delta: CaseDelta) -> dict[str, object]:
    return {
        "case_id": delta.case_id,
        "partition": delta.partition,
        "archetype": delta.archetype,
        "scores": dict(delta.scores),
        "deltas_from_previous": dict(delta.deltas_from_previous),
        "deltas_from_baseline": dict(delta.deltas_from_baseline),
    }


def _write_private_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        path.chmod(0o600)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)
        raise
