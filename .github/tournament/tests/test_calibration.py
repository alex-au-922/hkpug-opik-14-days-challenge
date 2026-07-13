from __future__ import annotations

import importlib.util
import json
import stat
import subprocess
import sys
from collections.abc import Callable
from dataclasses import FrozenInstanceError, dataclass
from hashlib import sha256
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

from hkpug_challenge.calibration import run_calibration, validate_calibration_paths
from hkpug_challenge.evaluation_bank import (
    ARCHETYPES,
    EvaluationBank,
    EvaluationCase,
    EvaluationReference,
    EvaluationRubric,
)
from hkpug_challenge.fireworks import (
    FIREWORKS_MODEL,
    JUDGE_MODEL,
    Completion,
    CompletionClient,
    JsonObject,
)
from hkpug_challenge.models import Message


PROFILE_NAMES = (
    "output_contract",
    "evidence_authority",
    "conflict_resistance",
    "uncertainty_escalation",
)
PROMPT_FILENAMES = tuple(f"attempt-{index:02d}.txt" for index in range(1, 5))
PRIVATE_PROMPT_BLOCKS = (
    "PRIVATE OUTPUT CONTRACT ALPHA",
    "PRIVATE AUTHORITY STRATEGY BETA",
    "PRIVATE CONFLICT STRATEGY GAMMA",
    "PRIVATE ESCALATION STRATEGY DELTA",
)


@pytest.fixture
def repository_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".gitignore").write_text(".local/\n", encoding="utf-8")
    return root


class UnusedClient:
    def complete(
        self,
        messages: tuple[Message, ...],
        *,
        max_tokens: int,
        response_format: JsonObject | None = None,
    ) -> Completion:
        raise AssertionError("The injected scorer must not call Fireworks clients.")


class StaticCompletionClient:
    def __init__(self, content: str) -> None:
        self._content = content
        self.call_count = 0

    def complete(
        self,
        messages: tuple[Message, ...],
        *,
        max_tokens: int,
        response_format: JsonObject | None = None,
    ) -> Completion:
        del messages, max_tokens, response_format
        self.call_count += 1
        return Completion(content=self._content, prompt_tokens=1, completion_tokens=1)


@dataclass(frozen=True)
class ScoreCall:
    attempt: int
    run_id: str
    participant_prompt: str
    cases: tuple[EvaluationCase, ...]
    candidate_model: str
    judge_model: str
    max_calls: int
    max_run_tokens: int
    include_holdout_details: bool


class FakeScorer:
    def __init__(
        self,
        bank: EvaluationBank,
        *,
        token_totals: tuple[int, int, int, int] = (
            400_000,
            400_000,
            400_000,
            400_000,
        ),
        return_holdout_details: bool = True,
        fabricate_case_score: bool = False,
    ) -> None:
        self._bank = bank
        self._token_totals = token_totals
        self._return_holdout_details = return_holdout_details
        self._fabricate_case_score = fabricate_case_score
        self.calls: list[ScoreCall] = []

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
    ) -> dict[str, Any]:
        del team_id, public_directory, candidate_client, judge_client
        self.calls.append(
            ScoreCall(
                attempt=attempt,
                run_id=run_id,
                participant_prompt=participant_prompt,
                cases=cases,
                candidate_model=candidate_model,
                judge_model=judge_model,
                max_calls=max_calls,
                max_run_tokens=max_run_tokens,
                include_holdout_details=include_holdout_details,
            )
        )
        if on_case_start is not None:
            for current in range(1, len(cases) + 1):
                on_case_start(current, len(cases))
        result = make_scoring_result(
            bank=self._bank,
            attempt=attempt,
            participant_prompt=participant_prompt,
            token_total=self._token_totals[attempt - 1],
        )
        if not self._return_holdout_details:
            holdout = cast(dict[str, Any], result["holdout"])
            del holdout["cases"]
        if self._fabricate_case_score:
            discovery = cast(dict[str, Any], result["discovery"])
            case_rows = cast(list[dict[str, Any]], discovery["cases"])
            case_rows[0]["score"] = float(case_rows[0]["score"]) + 1.0
        return result


def test_run_calibration_orders_profiles_and_requests_all_private_details(
    repository_root: Path,
) -> None:
    bank = make_bank()
    prompts = write_prompts(repository_root)
    scorer = FakeScorer(bank)
    progress: list[tuple[str, int, int]] = []

    result = run_calibration(
        bank=bank,
        repository_root=repository_root,
        prompt_directory=prompts,
        public_directory=repository_root / "public",
        output_path=repository_root / ".local/calibration/round.json",
        candidate_client=UnusedClient(),
        judge_client=UnusedClient(),
        scorer=scorer,
        on_progress=lambda profile, current, total: progress.append(
            (profile, current, total)
        ),
    )

    assert tuple(profile.name for profile in result.profiles) == PROFILE_NAMES
    assert [call.attempt for call in scorer.calls] == [1, 2, 3, 4]
    assert [call.participant_prompt for call in scorer.calls] == [
        cumulative_prompt(index) for index in range(1, 5)
    ]
    assert all(call.cases == bank.cases for call in scorer.calls)
    assert all(call.include_holdout_details for call in scorer.calls)
    assert all(call.candidate_model == FIREWORKS_MODEL for call in scorer.calls)
    assert all(call.judge_model == JUDGE_MODEL for call in scorer.calls)
    assert all(call.max_calls == 100 for call in scorer.calls)
    assert all(call.max_run_tokens == 500_000 for call in scorer.calls)
    assert len(progress) == 200
    assert progress[0] == ("output_contract", 1, 50)
    assert progress[-1] == ("uncertainty_escalation", 50, 50)
    assert all(profile.discovery.case_count == 40 for profile in result.profiles)
    assert all(profile.holdout.case_count == 10 for profile in result.profiles)


def test_run_calibration_integrates_real_score_prompt_with_private_holdout(
    repository_root: Path,
) -> None:
    bank = make_bank()
    public_directory = write_public_contexts(repository_root)
    candidate_client = StaticCompletionClient(
        json.dumps(
            {
                "answer": "Private answer.",
                "citations": ["ABC-DEF-001"],
                "escalate": False,
            }
        )
    )
    judge_client = StaticCompletionClient(
        json.dumps(
            {
                "answer_relevance": 100,
                "instruction_following": 100,
                "faithfulness": 100,
                "required_points_met": [0],
                "prohibited_claims_present": [],
                "non_authoritative_evidence_used": [],
                "reasons": {
                    "answer_relevance": "The required point is present.",
                    "instruction_following": "The output contract is followed.",
                    "faithfulness": "The answer follows authoritative evidence.",
                },
            }
        )
    )

    result = run_calibration(
        bank=bank,
        repository_root=repository_root,
        prompt_directory=write_prompts(repository_root),
        public_directory=public_directory,
        output_path=repository_root / ".local/calibration/real-score-prompt.json",
        candidate_client=candidate_client,
        judge_client=judge_client,
    )

    assert candidate_client.call_count == 200
    assert judge_client.call_count == 200
    assert len(result.profiles) == 4
    assert all(len(profile.diagnostics) == 50 for profile in result.profiles)
    assert all(profile.holdout.case_count == 10 for profile in result.profiles)


def test_run_calibration_rejects_non_cumulative_prompts(
    repository_root: Path,
) -> None:
    bank = make_bank()
    prompts = write_prompts(repository_root)
    (prompts / "attempt-03.txt").write_text(
        "PRIVATE REPLACEMENT STRATEGY",
        encoding="utf-8",
    )
    scorer = FakeScorer(bank)

    with pytest.raises(ValueError, match="cumulative"):
        run_calibration(
            bank=bank,
            repository_root=repository_root,
            prompt_directory=prompts,
            public_directory=repository_root / "public",
            output_path=repository_root / ".local/calibration/round.json",
            candidate_client=UnusedClient(),
            judge_client=UnusedClient(),
            scorer=scorer,
        )

    assert scorer.calls == []


def test_run_calibration_requires_exact_prompt_files(repository_root: Path) -> None:
    bank = make_bank()
    prompts = write_prompts(repository_root)
    (prompts / "notes.txt").write_text("private notes", encoding="utf-8")
    scorer = FakeScorer(bank)

    with pytest.raises(ValueError, match="exactly four"):
        run_calibration(
            bank=bank,
            repository_root=repository_root,
            prompt_directory=prompts,
            public_directory=repository_root / "public",
            output_path=repository_root / ".local/calibration/round.json",
            candidate_client=UnusedClient(),
            judge_client=UnusedClient(),
            scorer=scorer,
        )

    assert scorer.calls == []


def test_run_calibration_requires_returned_holdout_case_details(
    repository_root: Path,
) -> None:
    bank = make_bank()

    with pytest.raises(ValueError, match="private holdout case detail"):
        run_calibration(
            bank=bank,
            repository_root=repository_root,
            prompt_directory=write_prompts(repository_root),
            public_directory=repository_root / "public",
            output_path=repository_root / ".local/calibration/round.json",
            candidate_client=UnusedClient(),
            judge_client=UnusedClient(),
            scorer=FakeScorer(bank, return_holdout_details=False),
        )


def test_run_calibration_rejects_fabricated_per_case_scores(
    repository_root: Path,
) -> None:
    bank = make_bank()
    scorer = FakeScorer(bank, fabricate_case_score=True)
    output = repository_root / ".local/calibration/round.json"

    with pytest.raises(ValueError, match="rounded sum of its criteria"):
        run_calibration(
            bank=bank,
            repository_root=repository_root,
            prompt_directory=write_prompts(repository_root),
            public_directory=repository_root / "public",
            output_path=output,
            candidate_client=UnusedClient(),
            judge_client=UnusedClient(),
            scorer=scorer,
        )

    assert len(scorer.calls) == 1
    assert not output.exists()


def test_run_calibration_rejects_output_inside_public_contexts(
    repository_root: Path,
) -> None:
    bank = make_bank()
    public_directory = repository_root / ".local/public"
    public_directory.mkdir(parents=True)
    scorer = FakeScorer(bank)

    with pytest.raises(ValueError, match="outside the public directory"):
        run_calibration(
            bank=bank,
            repository_root=repository_root,
            prompt_directory=write_prompts(repository_root),
            public_directory=public_directory,
            output_path=public_directory / "private-round.json",
            candidate_client=UnusedClient(),
            judge_client=UnusedClient(),
            scorer=scorer,
        )

    assert scorer.calls == []
    assert list(public_directory.iterdir()) == []


@pytest.mark.parametrize("unsafe_path", ["prompt", "output"])
def test_validate_calibration_paths_rejects_paths_outside_repository_local_tree(
    repository_root: Path,
    unsafe_path: str,
) -> None:
    prompt_directory = write_prompts(repository_root)
    output_path = repository_root / ".local/calibration/round.json"
    if unsafe_path == "prompt":
        prompt_directory = write_prompts(
            repository_root,
            directory=repository_root / "prompts",
        )
    else:
        output_path = repository_root / "round.json"

    with pytest.raises(ValueError, match="repository .local tree"):
        validate_calibration_paths(
            repository_root=repository_root,
            prompt_directory=prompt_directory,
            public_directory=repository_root / "public",
            output_path=output_path,
        )


def test_validate_calibration_paths_rejects_non_ignored_local_tree(
    repository_root: Path,
) -> None:
    prompt_directory = write_prompts(repository_root)
    (repository_root / ".gitignore").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="not ignored"):
        validate_calibration_paths(
            repository_root=repository_root,
            prompt_directory=prompt_directory,
            public_directory=repository_root / "public",
            output_path=repository_root / ".local/calibration/round.json",
        )


@pytest.mark.parametrize("tracked_path", ["prompt", "output"])
def test_validate_calibration_paths_rejects_tracked_private_paths(
    repository_root: Path,
    tracked_path: str,
) -> None:
    prompt_directory = write_prompts(repository_root)
    output_path = repository_root / ".local/calibration/round.json"
    path_to_track = prompt_directory / "attempt-01.txt"
    if tracked_path == "output":
        output_path.write_text("tracked private report", encoding="utf-8")
        path_to_track = output_path
    subprocess.run(
        ["git", "-C", str(repository_root), "add", "-f", str(path_to_track)],
        check=True,
    )

    with pytest.raises(ValueError, match="tracked"):
        validate_calibration_paths(
            repository_root=repository_root,
            prompt_directory=prompt_directory,
            public_directory=repository_root / "public",
            output_path=output_path,
        )


def test_run_calibration_aggregates_archetypes_case_deltas_and_gates(
    repository_root: Path,
) -> None:
    bank = make_bank()
    result = run_calibration(
        bank=bank,
        repository_root=repository_root,
        prompt_directory=write_prompts(repository_root),
        public_directory=repository_root / "public",
        output_path=repository_root / ".local/calibration/round.json",
        candidate_client=UnusedClient(),
        judge_client=UnusedClient(),
        scorer=FakeScorer(bank),
    )

    final_archetypes = {
        aggregate.archetype: aggregate for aggregate in result.profiles[-1].archetypes
    }
    assert set(final_archetypes) == set(ARCHETYPES)
    assert all(aggregate.case_count == 10 for aggregate in final_archetypes.values())
    ambiguous = final_archetypes["ambiguous_authority_or_escalation"]
    assert dict(ambiguous.criteria)["escalation"] == 10.0

    conflict_case = next(
        delta
        for delta in result.case_deltas
        if delta.archetype == "conflicting_or_stale_evidence"
    )
    assert dict(conflict_case.scores) == {
        "output_contract": 40.0,
        "evidence_authority": 43.0,
        "conflict_resistance": 48.0,
        "uncertainty_escalation": 54.0,
    }
    assert dict(conflict_case.deltas_from_previous) == {
        "evidence_authority": 3.0,
        "conflict_resistance": 5.0,
        "uncertainty_escalation": 6.0,
    }
    assert dict(conflict_case.deltas_from_baseline)["uncertainty_escalation"] == 14.0

    gates = {gate.name: gate for gate in result.gates}
    assert gates["final_over_baseline"].actual == 12.0
    assert gates["authority_targeted_delta"].actual == 3.0
    assert gates["conflict_untrusted_delta"].actual == 5.0
    assert gates["ambiguous_escalation_delta"].actual == 11.0
    assert gates["final_escalation"].actual == 10.0
    assert gates["final_discovery_holdout_gap"].actual == 0.0
    assert all(gate.passed for gate in result.gates)
    assert result.passed is True


@pytest.mark.parametrize(
    ("token_total", "hard_passed", "target_passed"),
    [
        (425_001, True, False),
        (500_001, False, False),
    ],
)
def test_run_calibration_reports_hard_and_target_token_gates(
    repository_root: Path,
    token_total: int,
    hard_passed: bool,
    target_passed: bool,
) -> None:
    bank = make_bank()
    result = run_calibration(
        bank=bank,
        repository_root=repository_root,
        prompt_directory=write_prompts(repository_root),
        public_directory=repository_root / "public",
        output_path=repository_root / ".local/calibration/round.json",
        candidate_client=UnusedClient(),
        judge_client=UnusedClient(),
        scorer=FakeScorer(bank, token_totals=(400_000, 400_000, token_total, 400_000)),
    )

    gates = {gate.name: gate for gate in result.gates}
    assert gates["hard_token_limit"].actual == token_total
    assert gates["hard_token_limit"].passed is hard_passed
    assert gates["target_token_limit"].actual == token_total
    assert gates["target_token_limit"].passed is target_passed
    assert result.passed is (hard_passed and target_passed)


def test_run_calibration_writes_mode_0600_report_with_redacted_diagnostics(
    repository_root: Path,
) -> None:
    bank = make_bank()
    prompts = write_prompts(repository_root)
    output = repository_root / ".local/calibration/round.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text("old private report", encoding="utf-8")
    output.chmod(0o644)

    result = run_calibration(
        bank=bank,
        repository_root=repository_root,
        prompt_directory=prompts,
        public_directory=repository_root / "public",
        output_path=output,
        candidate_client=UnusedClient(),
        judge_client=UnusedClient(),
        scorer=FakeScorer(bank),
    )

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    report_text = output.read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert "PRIVATE OUTPUT CONTRACT ALPHA" not in report_text
    assert "PRIVATE CASE INPUT MUST NOT LEAK" not in report_text
    assert "PRIVATE CONTEXT MUST NOT LEAK" not in report_text
    assert "PRIVATE REFERENCE MUST NOT LEAK" not in report_text
    assert "PRIVATE RUBRIC MUST NOT LEAK" not in report_text
    assert "PRIVATE PARTICIPANT PROMPT MUST NOT LEAK" not in report_text
    assert "Private calibration question." not in report_text
    assert [profile["prompt_sha256"] for profile in report["profiles"]] == [
        sha256(cumulative_prompt(index).encode()).hexdigest() for index in range(1, 5)
    ]
    assert set(report["diagnostics"]) == set(PROFILE_NAMES)
    first_case_id = bank.cases[0].case_id
    diagnostic = report["diagnostics"]["output_contract"][first_case_id]
    assert set(diagnostic) == {"output", "criteria", "reasons", "judge"}
    assert diagnostic["output"] == "PRIVATE CASE OUTPUT MUST NOT LEAK"
    assert diagnostic["criteria"] == make_case_result(bank.cases[0], 1)["criteria"]
    assert diagnostic["reasons"] == make_case_result(bank.cases[0], 1)["reasons"]
    assert diagnostic["judge"] == make_case_result(bank.cases[0], 1)["judge"]
    assert all(
        set(profile_diagnostics) == {case.case_id for case in bank.cases}
        for profile_diagnostics in report["diagnostics"].values()
    )
    assert len(report["case_deltas"]) == 50
    assert report["passed"] is True
    with pytest.raises(FrozenInstanceError):
        setattr(result, "schema_version", 2)


def test_cli_fails_fast_before_loading_private_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_calibration_script()
    monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)

    def fail_private_load(*args: object, **kwargs: object) -> None:
        del args, kwargs
        pytest.fail("private bank must not be loaded")

    monkeypatch.setattr(
        module,
        "load_evaluation_bank",
        fail_private_load,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_calibration.py",
            "--evaluation-bank",
            str(tmp_path / "bank.json"),
            "--public-directory",
            str(tmp_path / "public"),
            "--prompt-directory",
            str(tmp_path / "prompts"),
            "--output",
            str(tmp_path / "round.json"),
        ],
    )

    assert module.main() == 1
    assert "FIREWORKS_API_KEY is required" in capsys.readouterr().err


def test_cli_rejects_wrong_models_before_loading_private_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_calibration_script()
    monkeypatch.setenv("FIREWORKS_API_KEY", "private-key")
    monkeypatch.setenv("FIREWORKS_MODEL", "accounts/fireworks/models/wrong")
    monkeypatch.setenv("JUDGE_MODEL", JUDGE_MODEL)

    def fail_private_load(*args: object, **kwargs: object) -> None:
        del args, kwargs
        pytest.fail("private bank must not be loaded")

    monkeypatch.setattr(module, "load_evaluation_bank", fail_private_load)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_calibration.py",
            "--evaluation-bank",
            str(tmp_path / "bank.json"),
            "--public-directory",
            str(tmp_path / "public"),
            "--prompt-directory",
            str(tmp_path / "prompts"),
            "--output",
            str(tmp_path / "round.json"),
        ],
    )

    assert module.main() == 1
    assert "FIREWORKS_MODEL must be" in capsys.readouterr().err


def test_cli_rejects_unsafe_paths_before_loading_private_inputs(
    repository_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_calibration_script()
    monkeypatch.setenv("FIREWORKS_API_KEY", "private-key")
    monkeypatch.setenv("FIREWORKS_MODEL", FIREWORKS_MODEL)
    monkeypatch.setenv("JUDGE_MODEL", JUDGE_MODEL)
    monkeypatch.setattr(
        module,
        "_authoritative_repository_root",
        lambda: repository_root,
        raising=False,
    )

    def fail_private_load(*args: object, **kwargs: object) -> None:
        del args, kwargs
        pytest.fail("private bank must not be loaded")

    monkeypatch.setattr(module, "load_evaluation_bank", fail_private_load)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_calibration.py",
            "--evaluation-bank",
            str(repository_root / ".local/evaluation/evaluation_bank.json"),
            "--public-directory",
            str(repository_root / "public"),
            "--prompt-directory",
            str(write_prompts(repository_root)),
            "--output",
            str(repository_root / "unsafe-round.json"),
        ],
    )

    assert module.main() == 1
    assert "repository .local tree" in capsys.readouterr().err


def make_bank() -> EvaluationBank:
    cases: list[EvaluationCase] = []
    for archetype in ARCHETYPES:
        for index in range(10):
            cases.append(
                EvaluationCase(
                    case_id=f"{archetype}-{index:02d}",
                    partition="discovery" if index < 8 else "holdout",
                    domain=f"domain-{index:02d}",
                    difficulty="hard",
                    archetype=archetype,
                    question="Private calibration question.",
                    context_files=("contexts/a.md", "contexts/b.md"),
                    reference=EvaluationReference(
                        answer="Private answer.",
                        citations=("ABC-DEF-001",),
                        escalate=False,
                        key_points=("Private point.",),
                    ),
                    rubric=EvaluationRubric(
                        required_citation_groups=(("ABC-DEF-001",),),
                        required_points=("Private point.",),
                        prohibited_claims=("Private prohibited claim.",),
                        non_authoritative_evidence=(),
                    ),
                )
            )
    return EvaluationBank(
        schema_version=1,
        dataset_version="private-v1",
        rubric_version="private-v1",
        cases=tuple(cases),
    )


def write_prompts(repository_root: Path, *, directory: Path | None = None) -> Path:
    prompt_directory = directory or repository_root / ".local/calibration/prompts"
    prompt_directory.mkdir(parents=True, exist_ok=True)
    for index, filename in enumerate(PROMPT_FILENAMES, start=1):
        (prompt_directory / filename).write_text(
            cumulative_prompt(index) + "\n",
            encoding="utf-8",
        )
    return prompt_directory


def write_public_contexts(repository_root: Path) -> Path:
    public_directory = repository_root / "public"
    context_directory = public_directory / "contexts"
    context_directory.mkdir(parents=True)
    (context_directory / "a.md").write_text(
        "# Primary\n\n## [ABC-DEF-001]\nPrivate answer.\n",
        encoding="utf-8",
    )
    (context_directory / "b.md").write_text(
        "# Secondary\n\n## [ABC-DEF-002]\nSupporting detail.\n",
        encoding="utf-8",
    )
    return public_directory


def cumulative_prompt(block_count: int) -> str:
    return "\n\n".join(PRIVATE_PROMPT_BLOCKS[:block_count])


def make_scoring_result(
    *,
    bank: EvaluationBank,
    attempt: int,
    participant_prompt: str,
    token_total: int,
) -> dict[str, Any]:
    rows = [make_case_result(case, attempt) for case in bank.cases]
    discovery_rows = [
        row
        for row, case in zip(rows, bank.cases, strict=True)
        if case.partition == "discovery"
    ]
    holdout_rows = [
        row
        for row, case in zip(rows, bank.cases, strict=True)
        if case.partition == "holdout"
    ]
    discovery = aggregate_rows(discovery_rows)
    holdout = aggregate_rows(holdout_rows)
    discovery["cases"] = discovery_rows
    holdout["cases"] = holdout_rows
    candidate_total = token_total // 2
    judge_total = token_total - candidate_total
    return {
        "schema_version": 1,
        "team_id": "organizer-calibration",
        "attempt": attempt,
        "run_id": f"calibration-{PROFILE_NAMES[attempt - 1]}",
        "model": FIREWORKS_MODEL,
        "judge_model": JUDGE_MODEL,
        "prompt_sha256": sha256(participant_prompt.strip().encode()).hexdigest(),
        "discovery": discovery,
        "holdout": holdout,
        "overall_score": round(
            float(discovery["score"]) * 0.75 + float(holdout["score"]) * 0.25,
            2,
        ),
        "token_usage": {
            "candidate": token_bucket(candidate_total),
            "judge": token_bucket(judge_total),
            "total": {
                "prompt_tokens": token_total - token_total // 10,
                "completion_tokens": token_total // 10,
                "total_tokens": token_total,
            },
        },
        "call_count": 100,
        "started_at": "2026-07-13T00:00:00.000Z",
        "completed_at": "2026-07-13T00:01:00.000Z",
    }


def make_case_result(case: EvaluationCase, attempt: int) -> dict[str, Any]:
    criteria = {
        "json_schema": 10.0,
        "citation_validity": 5.0,
        "evidence_coverage": 5.0,
        "escalation": (
            5.0 if case.archetype == "ambiguous_authority_or_escalation" else 10.0
        ),
        "answer_relevance": 5.0,
        "instruction_following": 0.0,
        "faithfulness": 5.0,
    }
    if attempt >= 2:
        criteria["evidence_coverage"] += 1.0
        criteria["faithfulness"] += 2.0
    if attempt >= 3 and case.archetype in {
        "conflicting_or_stale_evidence",
        "prompt_injection_or_untrusted_evidence",
    }:
        criteria["faithfulness"] += 5.0
    if attempt >= 4:
        criteria["answer_relevance"] += 6.0
        if case.archetype == "ambiguous_authority_or_escalation":
            criteria["escalation"] = 10.0
    faithfulness_cap = (
        "Faithfulness tier capped from 100 to 50: prohibited claim indexes: 0."
    )
    return {
        "case_id": case.case_id,
        "domain": case.domain,
        "difficulty": case.difficulty,
        "input": {
            "question": "PRIVATE CASE INPUT MUST NOT LEAK",
            "context": "PRIVATE CONTEXT MUST NOT LEAK",
        },
        "output": "PRIVATE CASE OUTPUT MUST NOT LEAK",
        "criteria": criteria,
        "score": round(sum(criteria.values()), 2),
        "reasons": {
            "answer_relevance": "PRIVATE RELEVANCE REASON",
            "instruction_following": "PRIVATE INSTRUCTION REASON",
            "faithfulness": faithfulness_cap,
        },
        "judge": {
            "raw_tiers": {
                "answer_relevance": 25,
                "instruction_following": 0,
                "faithfulness": 100,
            },
            "effective_tiers": {
                "answer_relevance": 25,
                "instruction_following": 0,
                "faithfulness": 50,
            },
            "audit": {
                "required_points_met": [0],
                "prohibited_claims_present": [0],
                "non_authoritative_evidence_used": [],
            },
            "cap_explanations": {"faithfulness": faithfulness_cap},
        },
        "reference": "PRIVATE REFERENCE MUST NOT LEAK",
        "rubric": "PRIVATE RUBRIC MUST NOT LEAK",
        "participant_prompt": "PRIVATE PARTICIPANT PROMPT MUST NOT LEAK",
    }


def aggregate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    criteria = {
        name: round(
            sum(float(row["criteria"][name]) for row in rows) / len(rows),
            2,
        )
        for name in rows[0]["criteria"]
    }
    return {
        "case_count": len(rows),
        "criteria": criteria,
        "score": round(sum(criteria.values()), 2),
    }


def token_bucket(total: int) -> dict[str, int]:
    completion = total // 10
    return {
        "prompt_tokens": total - completion,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def load_calibration_script() -> ModuleType:
    script_path = Path(__file__).parents[1] / "scripts/run_calibration.py"
    spec = importlib.util.spec_from_file_location("run_calibration_script", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
