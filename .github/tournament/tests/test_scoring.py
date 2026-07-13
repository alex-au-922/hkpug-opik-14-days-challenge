from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from hkpug_challenge.evaluation_bank import (
    EvaluationCase,
    EvaluationReference,
    EvaluationRubric,
)
from hkpug_challenge.fireworks import (
    Completion,
    FIREWORKS_MODEL,
    JUDGE_RESPONSE_FORMAT,
    SCORING_JUDGE_RESPONSE_FORMAT,
)
from hkpug_challenge.models import Message
from hkpug_challenge.playground import FIXED_SYSTEM_PROMPT
from hkpug_challenge.scoring import MAX_RUN_TOKENS, score_prompt


JUDGE_MODEL = "accounts/fireworks/models/qwen3p7-plus"


class FakeCompletionClient:
    def __init__(self, responses: Sequence[Completion | str]) -> None:
        self._responses = iter(responses)
        self.calls: list[tuple[tuple[Message, ...], int, dict[str, object] | None]] = []

    def complete(
        self,
        messages: tuple[Message, ...],
        *,
        max_tokens: int,
        response_format: dict[str, object] | None = None,
    ) -> Completion:
        self.calls.append((messages, max_tokens, response_format))
        response = next(self._responses)
        if isinstance(response, Completion):
            return response
        return Completion(content=response, prompt_tokens=100, completion_tokens=20)


def write_contexts(root: Path) -> Path:
    public = root / "public"
    contexts = public / "contexts"
    contexts.mkdir(parents=True)
    (contexts / "handbook.md").write_text(
        "# Handbook\n\n## [HB-GOV-001]\nUse active policy.\n",
        encoding="utf-8",
    )
    (contexts / "domain.md").write_text(
        (
            "# Domain\n\n"
            "## [DOM-POL-001]\nThe approved outcome is Alpha.\n\n"
            "## [DOM-POL-002]\nEscalation is not required.\n"
        ),
        encoding="utf-8",
    )
    return public


def make_case(case_id: str, partition: str) -> EvaluationCase:
    return EvaluationCase(
        case_id=case_id,
        partition=partition,
        domain="test-domain",
        difficulty="standard",
        archetype="multi_source_synthesis",
        question=f"What is the approved outcome for {case_id}?",
        context_files=("contexts/handbook.md", "contexts/domain.md"),
        reference=EvaluationReference(
            answer="The approved outcome is Alpha.",
            citations=("DOM-POL-001", "DOM-POL-002"),
            escalate=False,
            key_points=("State Alpha.", "Do not escalate."),
        ),
        rubric=EvaluationRubric(
            required_citation_groups=(("DOM-POL-001",), ("DOM-POL-002",)),
            required_points=("State Alpha.", "Do not escalate."),
            prohibited_claims=("Claim Beta.",),
            non_authoritative_evidence=("HB-GOV-001",),
        ),
    )


def make_cases() -> tuple[EvaluationCase, ...]:
    return tuple(
        [make_case(f"DISC-{index:02d}", "discovery") for index in range(1, 41)]
        + [make_case(f"HOLD-{index:02d}", "holdout") for index in range(1, 11)]
    )


def judge_response(
    relevance: int = 75,
    instruction: int = 100,
    faithfulness: int = 75,
    *,
    required_points_met: Sequence[int] = (0, 1),
    prohibited_claims_present: Sequence[int] = (),
    non_authoritative_evidence_used: Sequence[str] = (),
) -> str:
    return json.dumps(
        {
            "answer_relevance": relevance,
            "instruction_following": instruction,
            "faithfulness": faithfulness,
            "required_points_met": required_points_met,
            "prohibited_claims_present": prohibited_claims_present,
            "non_authoritative_evidence_used": non_authoritative_evidence_used,
            "reasons": {
                "answer_relevance": "Answers the requested decision.",
                "instruction_following": "Follows the response contract.",
                "faithfulness": "Claims match the supplied evidence.",
            },
        }
    )


def valid_answer() -> str:
    return json.dumps(
        {
            "answer": "The approved outcome is Alpha.",
            "citations": ["DOM-POL-001", "DOM-POL-002"],
            "escalate": False,
        }
    )


def test_score_prompt_returns_discovery_detail_and_hides_holdout_by_default(
    tmp_path: Path,
) -> None:
    public = write_contexts(tmp_path)
    answer_client = FakeCompletionClient([valid_answer()] * 50)
    judge_client = FakeCompletionClient([judge_response()] * 50)

    result = score_prompt(
        team_id="team-01",
        attempt=1,
        run_id="run-001",
        participant_prompt="Use evidence and return strict JSON.",
        cases=make_cases(),
        public_directory=public,
        candidate_client=answer_client,
        judge_client=judge_client,
    )

    assert len(answer_client.calls) == 50
    assert len(judge_client.calls) == 50
    assert all(call[1:] == (256, None) for call in answer_client.calls)
    assert all(
        call[1:] == (1024, SCORING_JUDGE_RESPONSE_FORMAT) for call in judge_client.calls
    )
    for audit_field in (
        "required_points_met",
        "prohibited_claims_present",
        "non_authoritative_evidence_used",
    ):
        assert audit_field not in json.dumps(JUDGE_RESPONSE_FORMAT)
        assert audit_field in json.dumps(SCORING_JUDGE_RESPONSE_FORMAT)
    assert result["model"] == FIREWORKS_MODEL
    assert result["judge_model"] == JUDGE_MODEL
    assert result["overall_score"] == 88.75
    assert result["discovery"]["score"] == 88.75
    assert result["holdout"]["score"] == 88.75
    assert len(result["discovery"]["cases"]) == 40
    assert "cases" not in result["holdout"]
    assert result["token_usage"] == {
        "candidate": {
            "prompt_tokens": 5000,
            "completion_tokens": 1000,
            "total_tokens": 6000,
        },
        "judge": {
            "prompt_tokens": 5000,
            "completion_tokens": 1000,
            "total_tokens": 6000,
        },
        "total": {
            "prompt_tokens": 10000,
            "completion_tokens": 2000,
            "total_tokens": 12000,
        },
    }
    assert result["call_count"] == 100
    serialized = json.dumps(result)
    assert "Use evidence and return strict JSON" not in serialized
    assert "The approved outcome is Alpha." in serialized
    assert "HOLD-01" not in serialized
    assert "reference" not in serialized
    assert "rubric" not in serialized
    assert "participant_prompt" in answer_client.calls[0][0][-1]["content"]
    assert "participant_prompt" not in judge_client.calls[0][0][-1]["content"]


def test_score_prompt_includes_all_holdout_details_when_requested(
    tmp_path: Path,
) -> None:
    public = write_contexts(tmp_path)

    result = score_prompt(
        team_id="team-01",
        attempt=1,
        run_id="run-private-holdout",
        participant_prompt="Return JSON.",
        cases=make_cases(),
        public_directory=public,
        candidate_client=FakeCompletionClient([valid_answer()] * 50),
        judge_client=FakeCompletionClient([judge_response()] * 50),
        include_holdout_details=True,
    )

    holdout_cases = result["holdout"]["cases"]
    assert len(holdout_cases) == 10
    assert [case["case_id"] for case in holdout_cases] == [
        f"HOLD-{index:02d}" for index in range(1, 11)
    ]
    assert set(holdout_cases[0]) == set(result["discovery"]["cases"][0])
    assert all("partition" not in case for case in holdout_cases)


def test_score_prompt_reports_case_progress_without_case_details(
    tmp_path: Path,
) -> None:
    public = write_contexts(tmp_path)
    progress: list[tuple[int, int]] = []

    score_prompt(
        team_id="team-01",
        attempt=1,
        run_id="run-progress",
        participant_prompt="Return JSON.",
        cases=make_cases(),
        public_directory=public,
        candidate_client=FakeCompletionClient([valid_answer()] * 50),
        judge_client=FakeCompletionClient([judge_response()] * 50),
        on_case_start=lambda current, total: progress.append((current, total)),
    )

    assert progress == [(current, 50) for current in range(1, 51)]


def test_score_prompt_applies_partial_deterministic_scores(tmp_path: Path) -> None:
    public = write_contexts(tmp_path)
    partial_answer = json.dumps(
        {
            "answer": "Alpha.",
            "citations": ["DOM-POL-001"],
            "escalate": False,
        }
    )

    result = score_prompt(
        team_id="team-01",
        attempt=2,
        run_id="run-002",
        participant_prompt="Return JSON.",
        cases=make_cases(),
        public_directory=public,
        candidate_client=FakeCompletionClient([partial_answer] * 50),
        judge_client=FakeCompletionClient([judge_response(50, 100, 50)] * 50),
    )

    assert result["overall_score"] == 72.5
    assert result["discovery"]["criteria"]["evidence_coverage"] == 5.0


def test_score_prompt_caps_relevance_by_required_point_coverage(
    tmp_path: Path,
) -> None:
    public = write_contexts(tmp_path)
    response = judge_response(
        100,
        0,
        0,
        required_points_met=(0,),
    )

    result = score_prompt(
        team_id="team-01",
        attempt=1,
        run_id="run-relevance-cap",
        participant_prompt="Return JSON.",
        cases=make_cases(),
        public_directory=public,
        candidate_client=FakeCompletionClient([valid_answer()] * 50),
        judge_client=FakeCompletionClient([response] * 50),
    )

    assert result["discovery"]["criteria"]["answer_relevance"] == 10.0
    assert result["holdout"]["criteria"]["answer_relevance"] == 10.0


@pytest.mark.parametrize(
    ("audit_field", "audit_value"),
    [
        ("prohibited_claims_present", [0]),
        ("non_authoritative_evidence_used", ["HB-GOV-001"]),
    ],
)
def test_score_prompt_caps_faithfulness_for_semantic_hazards(
    tmp_path: Path,
    audit_field: str,
    audit_value: list[int] | list[str],
) -> None:
    public = write_contexts(tmp_path)
    response = json.loads(judge_response(0, 0, 100))
    response[audit_field] = audit_value

    result = score_prompt(
        team_id="team-01",
        attempt=1,
        run_id="run-faithfulness-cap",
        participant_prompt="Return JSON.",
        cases=make_cases(),
        public_directory=public,
        candidate_client=FakeCompletionClient([valid_answer()] * 50),
        judge_client=FakeCompletionClient([json.dumps(response)] * 50),
    )

    assert result["discovery"]["criteria"]["faithfulness"] == 12.5
    assert result["holdout"]["criteria"]["faithfulness"] == 12.5


@pytest.mark.parametrize(
    ("audit_field", "audit_value"),
    [
        ("required_points_met", [-1]),
        ("required_points_met", [2]),
        ("prohibited_claims_present", [1]),
        ("non_authoritative_evidence_used", ["DOM-POL-001"]),
    ],
)
def test_score_prompt_rejects_semantic_audit_values_outside_case_rubric(
    tmp_path: Path,
    audit_field: str,
    audit_value: list[int] | list[str],
) -> None:
    public = write_contexts(tmp_path)
    response = json.loads(judge_response())
    response[audit_field] = audit_value

    with pytest.raises(ValueError, match="Judge response"):
        score_prompt(
            team_id="team-01",
            attempt=1,
            run_id="run-invalid-semantic-audit",
            participant_prompt="Return JSON.",
            cases=make_cases(),
            public_directory=public,
            candidate_client=FakeCompletionClient([valid_answer()] * 50),
            judge_client=FakeCompletionClient([json.dumps(response)]),
        )


def test_score_prompt_enforces_call_ceiling_before_model_calls(tmp_path: Path) -> None:
    public = write_contexts(tmp_path)
    answer_client = FakeCompletionClient([])
    judge_client = FakeCompletionClient([])

    with pytest.raises(ValueError, match="call limit"):
        score_prompt(
            team_id="team-01",
            attempt=1,
            run_id="run-003",
            participant_prompt="Return JSON.",
            cases=make_cases(),
            public_directory=public,
            candidate_client=answer_client,
            judge_client=judge_client,
            max_calls=99,
        )

    assert answer_client.calls == []
    assert judge_client.calls == []


def test_score_prompt_uses_documented_default_run_token_limit(tmp_path: Path) -> None:
    public = write_contexts(tmp_path)
    answer_client = FakeCompletionClient(
        [
            Completion(
                content=valid_answer(),
                prompt_tokens=MAX_RUN_TOKENS,
                completion_tokens=1,
            )
        ]
    )
    judge_client = FakeCompletionClient([])

    with pytest.raises(ValueError, match="500000 token limit"):
        score_prompt(
            team_id="team-01",
            attempt=1,
            run_id="run-over-budget-default",
            participant_prompt="Return JSON.",
            cases=make_cases(),
            public_directory=public,
            candidate_client=answer_client,
            judge_client=judge_client,
        )

    assert len(answer_client.calls) == 1
    assert judge_client.calls == []


def test_score_prompt_rejects_cumulative_usage_above_configured_limit(
    tmp_path: Path,
) -> None:
    public = write_contexts(tmp_path)
    answer_client = FakeCompletionClient(
        [
            Completion(content=valid_answer(), prompt_tokens=100, completion_tokens=20),
            Completion(content=valid_answer(), prompt_tokens=100, completion_tokens=20),
        ]
    )
    judge_client = FakeCompletionClient(
        [
            Completion(
                content=judge_response(),
                prompt_tokens=100,
                completion_tokens=20,
            )
        ]
    )

    with pytest.raises(ValueError, match="250 token limit"):
        score_prompt(
            team_id="team-01",
            attempt=1,
            run_id="run-over-budget-configured",
            participant_prompt="Return JSON.",
            cases=make_cases(),
            public_directory=public,
            candidate_client=answer_client,
            judge_client=judge_client,
            max_run_tokens=250,
        )

    assert len(answer_client.calls) == 2
    assert len(judge_client.calls) == 1


def test_fixed_system_prompt_is_a_neutral_transport_wrapper() -> None:
    assert (
        FIXED_SYSTEM_PROMPT
        == "You are running a support-answer prompt tournament. Follow the "
        "participant prompt to answer the supplied question."
    )
    system_prompt = FIXED_SYSTEM_PROMPT.casefold()
    for forbidden in (
        "context",
        "data",
        "authority",
        "authoritative",
        "citation",
        "inject",
        "escalat",
    ):
        assert forbidden not in system_prompt


def test_score_prompt_requires_all_fifty_cases_before_model_calls(
    tmp_path: Path,
) -> None:
    public = write_contexts(tmp_path)
    answer_client = FakeCompletionClient([])
    judge_client = FakeCompletionClient([])

    with pytest.raises(ValueError, match="40 discovery and 10 holdout"):
        score_prompt(
            team_id="team-01",
            attempt=1,
            run_id="run-incomplete",
            participant_prompt="Return JSON.",
            cases=make_cases()[:-1],
            public_directory=public,
            candidate_client=answer_client,
            judge_client=judge_client,
        )

    assert answer_client.calls == []
    assert judge_client.calls == []


def test_score_prompt_requires_a_distinct_judge_model(tmp_path: Path) -> None:
    public = write_contexts(tmp_path)
    answer_client = FakeCompletionClient([])
    judge_client = FakeCompletionClient([])

    with pytest.raises(ValueError, match="Judge model must differ"):
        score_prompt(
            team_id="team-01",
            attempt=1,
            run_id="run-same-model",
            participant_prompt="Return JSON.",
            cases=make_cases(),
            public_directory=public,
            candidate_client=answer_client,
            judge_client=judge_client,
            judge_model=FIREWORKS_MODEL,
        )

    assert answer_client.calls == []
    assert judge_client.calls == []


@pytest.mark.parametrize(
    ("candidate_model", "judge_model", "message"),
    [
        ("accounts/fireworks/models/other", JUDGE_MODEL, "FIREWORKS_MODEL"),
        (FIREWORKS_MODEL, "accounts/fireworks/models/other", "JUDGE_MODEL"),
    ],
)
def test_score_prompt_rejects_unapproved_model_configuration_before_calls(
    tmp_path: Path,
    candidate_model: str,
    judge_model: str,
    message: str,
) -> None:
    public = write_contexts(tmp_path)
    answer_client = FakeCompletionClient([])
    judge_client = FakeCompletionClient([])

    with pytest.raises(ValueError, match=message):
        score_prompt(
            team_id="team-01",
            attempt=1,
            run_id="run-invalid-model",
            participant_prompt="Return JSON.",
            cases=make_cases(),
            public_directory=public,
            candidate_client=answer_client,
            judge_client=judge_client,
            candidate_model=candidate_model,
            judge_model=judge_model,
        )

    assert answer_client.calls == []
    assert judge_client.calls == []


def test_score_prompt_does_not_retry_invalid_judge_output(tmp_path: Path) -> None:
    public = write_contexts(tmp_path)
    answer_client = FakeCompletionClient([valid_answer()] * 50)
    judge_client = FakeCompletionClient(["not-json"])

    with pytest.raises(ValueError, match="Judge response"):
        score_prompt(
            team_id="team-01",
            attempt=1,
            run_id="run-004",
            participant_prompt="Return JSON.",
            cases=make_cases(),
            public_directory=public,
            candidate_client=answer_client,
            judge_client=judge_client,
        )

    assert len(answer_client.calls) == 1
    assert len(judge_client.calls) == 1


@pytest.mark.parametrize(
    "criterion",
    ["answer_relevance", "instruction_following", "faithfulness"],
)
def test_score_prompt_rejects_non_tier_judge_scores(
    tmp_path: Path, criterion: str
) -> None:
    public = write_contexts(tmp_path)
    response = json.loads(judge_response())
    response[criterion] = 80

    with pytest.raises(ValueError, match="Judge response"):
        score_prompt(
            team_id="team-01",
            attempt=1,
            run_id="run-invalid-tier",
            participant_prompt="Return JSON.",
            cases=make_cases(),
            public_directory=public,
            candidate_client=FakeCompletionClient([valid_answer()] * 50),
            judge_client=FakeCompletionClient([json.dumps(response)]),
        )


def test_score_prompt_preserves_granularity_across_all_fifty_cases(
    tmp_path: Path,
) -> None:
    public = write_contexts(tmp_path)
    judge_responses = [judge_response(25, 0, 0)] + [judge_response(0, 0, 0)] * 49

    result = score_prompt(
        team_id="team-01",
        attempt=1,
        run_id="run-granular",
        participant_prompt="Return JSON.",
        cases=make_cases(),
        public_directory=public,
        candidate_client=FakeCompletionClient([valid_answer()] * 50),
        judge_client=FakeCompletionClient(judge_responses),
    )

    assert result["discovery"]["criteria"]["answer_relevance"] == 0.12
    assert result["discovery"]["score"] == 40.12
    assert result["holdout"]["score"] == 40.0
    assert result["overall_score"] == 40.09
