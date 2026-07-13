from __future__ import annotations

import importlib.util
import json
import stat
import sys
from collections.abc import Callable
from dataclasses import FrozenInstanceError, dataclass
from hashlib import sha256
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

from hkpug_challenge.calibration import run_calibration
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


class UnusedClient:
    def complete(
        self,
        messages: tuple[Message, ...],
        *,
        max_tokens: int,
        response_format: JsonObject | None = None,
    ) -> Completion:
        raise AssertionError("The injected scorer must not call Fireworks clients.")


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
    ) -> None:
        self._bank = bank
        self._token_totals = token_totals
        self._return_holdout_details = return_holdout_details
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
        return result


def test_run_calibration_orders_profiles_and_requests_all_private_details(
    tmp_path: Path,
) -> None:
    bank = make_bank()
    prompts = write_prompts(tmp_path)
    scorer = FakeScorer(bank)
    progress: list[tuple[str, int, int]] = []

    result = run_calibration(
        bank=bank,
        prompt_directory=prompts,
        public_directory=tmp_path / "public",
        output_path=tmp_path / "round.json",
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


def test_run_calibration_rejects_non_cumulative_prompts(tmp_path: Path) -> None:
    bank = make_bank()
    prompts = write_prompts(tmp_path)
    (prompts / "attempt-03.txt").write_text(
        "PRIVATE REPLACEMENT STRATEGY",
        encoding="utf-8",
    )
    scorer = FakeScorer(bank)

    with pytest.raises(ValueError, match="cumulative"):
        run_calibration(
            bank=bank,
            prompt_directory=prompts,
            public_directory=tmp_path / "public",
            output_path=tmp_path / "round.json",
            candidate_client=UnusedClient(),
            judge_client=UnusedClient(),
            scorer=scorer,
        )

    assert scorer.calls == []


def test_run_calibration_requires_exact_prompt_files(tmp_path: Path) -> None:
    bank = make_bank()
    prompts = write_prompts(tmp_path)
    (prompts / "notes.txt").write_text("private notes", encoding="utf-8")
    scorer = FakeScorer(bank)

    with pytest.raises(ValueError, match="exactly four"):
        run_calibration(
            bank=bank,
            prompt_directory=prompts,
            public_directory=tmp_path / "public",
            output_path=tmp_path / "round.json",
            candidate_client=UnusedClient(),
            judge_client=UnusedClient(),
            scorer=scorer,
        )

    assert scorer.calls == []


def test_run_calibration_requires_returned_holdout_case_details(
    tmp_path: Path,
) -> None:
    bank = make_bank()

    with pytest.raises(ValueError, match="private holdout case detail"):
        run_calibration(
            bank=bank,
            prompt_directory=write_prompts(tmp_path),
            public_directory=tmp_path / "public",
            output_path=tmp_path / "round.json",
            candidate_client=UnusedClient(),
            judge_client=UnusedClient(),
            scorer=FakeScorer(bank, return_holdout_details=False),
        )


def test_run_calibration_rejects_output_inside_public_contexts(
    tmp_path: Path,
) -> None:
    bank = make_bank()
    public_directory = tmp_path / "public"
    public_directory.mkdir()
    scorer = FakeScorer(bank)

    with pytest.raises(ValueError, match="outside the public directory"):
        run_calibration(
            bank=bank,
            prompt_directory=write_prompts(tmp_path),
            public_directory=public_directory,
            output_path=public_directory / "private-round.json",
            candidate_client=UnusedClient(),
            judge_client=UnusedClient(),
            scorer=scorer,
        )

    assert scorer.calls == []
    assert list(public_directory.iterdir()) == []


def test_run_calibration_aggregates_archetypes_case_deltas_and_gates(
    tmp_path: Path,
) -> None:
    bank = make_bank()
    result = run_calibration(
        bank=bank,
        prompt_directory=write_prompts(tmp_path),
        public_directory=tmp_path / "public",
        output_path=tmp_path / "round.json",
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
    tmp_path: Path,
    token_total: int,
    hard_passed: bool,
    target_passed: bool,
) -> None:
    bank = make_bank()
    result = run_calibration(
        bank=bank,
        prompt_directory=write_prompts(tmp_path),
        public_directory=tmp_path / "public",
        output_path=tmp_path / "round.json",
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


def test_run_calibration_writes_redacted_mode_0600_report(tmp_path: Path) -> None:
    bank = make_bank()
    prompts = write_prompts(tmp_path)
    output = tmp_path / "calibration" / "round.json"
    output.parent.mkdir()
    output.write_text("old private report", encoding="utf-8")
    output.chmod(0o644)

    result = run_calibration(
        bank=bank,
        prompt_directory=prompts,
        public_directory=tmp_path / "public",
        output_path=output,
        candidate_client=UnusedClient(),
        judge_client=UnusedClient(),
        scorer=FakeScorer(bank),
    )

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    report_text = output.read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert "PRIVATE OUTPUT CONTRACT ALPHA" not in report_text
    assert "PRIVATE CASE OUTPUT MUST NOT LEAK" not in report_text
    assert [profile["prompt_sha256"] for profile in report["profiles"]] == [
        sha256(cumulative_prompt(index).encode()).hexdigest() for index in range(1, 5)
    ]
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


def write_prompts(tmp_path: Path) -> Path:
    prompt_directory = tmp_path / "prompts"
    prompt_directory.mkdir(exist_ok=True)
    for index, filename in enumerate(PROMPT_FILENAMES, start=1):
        (prompt_directory / filename).write_text(
            cumulative_prompt(index) + "\n",
            encoding="utf-8",
        )
    return prompt_directory


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
    return {
        "case_id": case.case_id,
        "domain": case.domain,
        "difficulty": case.difficulty,
        "input": {"question": "PRIVATE CASE INPUT MUST NOT LEAK"},
        "output": "PRIVATE CASE OUTPUT MUST NOT LEAK",
        "criteria": criteria,
        "score": round(sum(criteria.values()), 2),
        "reasons": {"faithfulness": "PRIVATE REASON MUST NOT LEAK"},
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
