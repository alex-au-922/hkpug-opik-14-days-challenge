from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from hkpug_challenge.evaluation_bank import (
    EvaluationCase,
    EvaluationReference,
    EvaluationRubric,
)
from hkpug_challenge.fireworks import (
    Completion,
    EXPERIMENTAL_CANDIDATE_MAX_TOKENS,
    FIREWORKS_MODEL,
    JUDGE_RESPONSE_FORMAT,
    SCORING_JUDGE_RESPONSE_FORMAT,
    scoring_judge_response_format,
)
from hkpug_challenge.models import Message
from hkpug_challenge.playground import FIXED_SYSTEM_PROMPT
from hkpug_challenge.scoring import (
    JUDGE_MAX_TOKENS,
    MAX_RUN_CALLS,
    MAX_RUN_TOKENS,
    score_case,
    score_prompt,
)
from hkpug_challenge.traces import build_trace_bundle


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
    (contexts / "company_handbook.md").write_text(
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
        context_files=("contexts/company_handbook.md", "contexts/domain.md"),
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
    expected_judge_format = scoring_judge_response_format(
        required_point_count=2,
        prohibited_claim_count=1,
        non_authoritative_evidence=("HB-GOV-001",),
    )
    assert all(
        call[1:] == (JUDGE_MAX_TOKENS, expected_judge_format)
        for call in judge_client.calls
    )
    json_schema = cast(dict[str, object], expected_judge_format["json_schema"])
    schema = cast(dict[str, object], json_schema["schema"])
    scoring_properties = cast(dict[str, object], schema["properties"])

    def audit_enum(name: str) -> object:
        field = cast(dict[str, object], scoring_properties[name])
        items = cast(dict[str, object], field["items"])
        return items["enum"]

    assert audit_enum("required_points_met") == (0, 1)
    assert audit_enum("prohibited_claims_present") == (0,)
    assert audit_enum("non_authoritative_evidence_used") == ("HB-GOV-001",)
    for audit_field in (
        "required_points_met",
        "prohibited_claims_present",
        "non_authoritative_evidence_used",
    ):
        assert audit_field not in json.dumps(JUDGE_RESPONSE_FORMAT)
        assert audit_field in json.dumps(SCORING_JUDGE_RESPONSE_FORMAT)
    scoring_schema = json.dumps(SCORING_JUDGE_RESPONSE_FORMAT)
    assert '"minimum"' not in scoring_schema
    assert '"uniqueItems": true' in scoring_schema
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

    assert result["discovery"]["cases"][0]["judge"] == {
        "raw_tiers": {
            "answer_relevance": 75,
            "instruction_following": 100,
            "faithfulness": 75,
        },
        "effective_tiers": {
            "answer_relevance": 75,
            "instruction_following": 100,
            "faithfulness": 75,
        },
        "audit": {
            "required_points_met": [0, 1],
            "prohibited_claims_present": [],
            "non_authoritative_evidence_used": [],
        },
        "cap_explanations": {},
    }
    serialized = json.dumps(result)
    assert "Use evidence and return strict JSON" not in serialized
    assert "The approved outcome is Alpha." in serialized
    assert "HOLD-01" not in serialized
    assert "reference" not in serialized
    assert "rubric" not in serialized
    assert "participant_prompt" in answer_client.calls[0][0][-1]["content"]
    assert "participant_prompt" not in judge_client.calls[0][0][-1]["content"]
    assert "supplied context" in judge_client.calls[0][0][0]["content"]
    judge_payload = json.loads(judge_client.calls[0][0][-1]["content"])
    assert set(judge_payload) == {
        "question",
        "context",
        "candidate_answer",
        "reference",
        "rubric",
    }
    assert "# Source file: contexts/company_handbook.md" not in judge_payload["context"]
    assert "# Source file: contexts/domain.md" in judge_payload["context"]

    bundle = build_trace_bundle(result)
    assert len(bundle["trace_payload.json"]["traces"]) == 40
    assert len(bundle["span_payload.json"]["spans"]) == 80
    serialized_bundle = json.dumps(bundle)
    assert "HOLD-01" not in serialized_bundle
    assert "holdout question" not in serialized_bundle


def test_score_prompt_uses_longer_budget_for_experimental_candidate(
    tmp_path: Path,
) -> None:
    public = write_contexts(tmp_path)
    answer_client = FakeCompletionClient([valid_answer()] * 50)
    judge_client = FakeCompletionClient([judge_response()] * 50)
    candidate_model = "accounts/fireworks/models/gpt-oss-20b"

    score_prompt(
        team_id="team-01",
        attempt=1,
        run_id="run-gpt-oss",
        participant_prompt="Use evidence and return strict JSON.",
        cases=make_cases(),
        public_directory=public,
        candidate_client=answer_client,
        judge_client=judge_client,
        candidate_model=candidate_model,
        allow_experimental_candidate=True,
    )

    assert all(
        call[1] == EXPERIMENTAL_CANDIDATE_MAX_TOKENS for call in answer_client.calls
    )


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


def test_score_prompt_omits_unavailable_judge_audits(tmp_path: Path) -> None:
    public = write_contexts(tmp_path)
    cases = tuple(
        replace(
            case,
            rubric=replace(case.rubric, non_authoritative_evidence=()),
        )
        for case in make_cases()
    )
    response = json.loads(judge_response())
    del response["non_authoritative_evidence_used"]
    judge_client = FakeCompletionClient([json.dumps(response)] * 50)

    result = score_prompt(
        team_id="team-01",
        attempt=1,
        run_id="run-no-authority-audit",
        participant_prompt="Return JSON.",
        cases=cases,
        public_directory=public,
        candidate_client=FakeCompletionClient([valid_answer()] * 50),
        judge_client=judge_client,
    )

    response_format = cast(dict[str, object], judge_client.calls[0][2])
    json_schema = cast(dict[str, object], response_format["json_schema"])
    schema = cast(dict[str, object], json_schema["schema"])
    properties = cast(dict[str, object], schema["properties"])
    required = cast(list[str], schema["required"])
    assert "non_authoritative_evidence_used" not in properties
    assert "non_authoritative_evidence_used" not in required
    assert (
        result["discovery"]["cases"][0]["judge"]["audit"][
            "non_authoritative_evidence_used"
        ]
        == []
    )


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


def test_score_case_caps_instruction_following_for_manager_review_points(
    tmp_path: Path,
) -> None:
    case = replace(
        make_case("MANAGER-01", "discovery"),
        rubric=replace(
            make_case("MANAGER-01", "discovery").rubric,
            required_points=(
                "State Alpha.",
                "Manager review states the controlling evidence.",
                "Manager review explains the decision condition.",
            ),
        ),
    )
    response = judge_response(
        instruction=100,
        required_points_met=(0, 1),
    )
    token_usage = {
        bucket: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        for bucket in ("candidate", "judge", "total")
    }

    result = score_case(
        case=case,
        participant_prompt="Return JSON.",
        public_directory=write_contexts(tmp_path),
        candidate_client=FakeCompletionClient([valid_answer()]),
        judge_client=FakeCompletionClient([response]),
        candidate_model=FIREWORKS_MODEL,
        token_usage=token_usage,
        max_run_tokens=MAX_RUN_TOKENS,
    )

    assert result["judge"]["raw_tiers"]["instruction_following"] == 100
    assert result["judge"]["effective_tiers"]["instruction_following"] == 50
    reason = result["reasons"]["instruction_following"]
    assert "capped from 100 to 50" in reason
    assert "1 of 2 manager-review points" in reason


def test_score_case_leaves_instruction_following_uncapped_without_manager_review_points(
    tmp_path: Path,
) -> None:
    result = score_case(
        case=make_case("NO-MANAGER-01", "discovery"),
        participant_prompt="Return JSON.",
        public_directory=write_contexts(tmp_path),
        candidate_client=FakeCompletionClient([valid_answer()]),
        judge_client=FakeCompletionClient(
            [judge_response(instruction=100, required_points_met=())]
        ),
        candidate_model=FIREWORKS_MODEL,
        token_usage={
            bucket: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            for bucket in ("candidate", "judge", "total")
        },
        max_run_tokens=MAX_RUN_TOKENS,
    )

    assert result["judge"]["effective_tiers"]["instruction_following"] == 100
    assert "instruction_following" not in result["judge"]["cap_explanations"]
    assert result["reasons"]["instruction_following"] == (
        "Follows the response contract."
    )


def test_score_prompt_publishes_manager_review_instruction_cap_reason(
    tmp_path: Path,
) -> None:
    base_case = make_case("MANAGER", "discovery")
    manager_case = replace(
        base_case,
        rubric=replace(
            base_case.rubric,
            required_points=(
                "Manager review identifies the controlling evidence.",
                "Manager review explains the decision condition.",
            ),
        ),
    )
    cases = tuple(
        replace(manager_case, case_id=f"DISC-{index:02d}") for index in range(1, 41)
    ) + tuple(
        replace(manager_case, case_id=f"HOLD-{index:02d}", partition="holdout")
        for index in range(1, 11)
    )

    result = score_prompt(
        team_id="team-01",
        attempt=1,
        run_id="run-manager-review-cap",
        participant_prompt="Return JSON.",
        cases=cases,
        public_directory=write_contexts(tmp_path),
        candidate_client=FakeCompletionClient([valid_answer()] * 50),
        judge_client=FakeCompletionClient(
            [judge_response(required_points_met=(0,))] * 50
        ),
    )

    reason = result["discovery"]["cases"][0]["reasons"]["instruction_following"]
    assert "capped from 100 to 50" in reason
    assert "1 of 2 manager-review points" in reason


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


def test_score_prompt_retains_cap_audit_and_publishes_cap_safe_reasons(
    tmp_path: Path,
) -> None:
    public = write_contexts(tmp_path)
    response = json.loads(
        judge_response(
            100,
            100,
            100,
            required_points_met=(0,),
            prohibited_claims_present=(0,),
            non_authoritative_evidence_used=("HB-GOV-001",),
        )
    )
    response["reasons"] = {
        "answer_relevance": "Fully met.",
        "instruction_following": "Fully met.",
        "faithfulness": "Fully met.",
    }

    result = score_prompt(
        team_id="team-01",
        attempt=1,
        run_id="run-auditable-caps",
        participant_prompt="Return JSON.",
        cases=make_cases(),
        public_directory=public,
        candidate_client=FakeCompletionClient([valid_answer()] * 50),
        judge_client=FakeCompletionClient([json.dumps(response)] * 50),
    )

    case = result["discovery"]["cases"][0]
    assert case["judge"]["raw_tiers"] == {
        "answer_relevance": 100,
        "instruction_following": 100,
        "faithfulness": 100,
    }
    assert case["judge"]["effective_tiers"] == {
        "answer_relevance": 50,
        "instruction_following": 100,
        "faithfulness": 50,
    }
    assert case["judge"]["audit"] == {
        "required_points_met": [0],
        "prohibited_claims_present": [0],
        "non_authoritative_evidence_used": ["HB-GOV-001"],
    }
    cap_explanations = case["judge"]["cap_explanations"]
    assert set(cap_explanations) == {"answer_relevance", "faithfulness"}
    assert "capped from 100 to 50" in cap_explanations["answer_relevance"]
    assert "1 of 2 required points" in cap_explanations["answer_relevance"]
    assert "capped from 100 to 50" in cap_explanations["faithfulness"]
    assert "prohibited claim indexes: 0" in cap_explanations["faithfulness"]
    assert (
        "non-authoritative evidence IDs: HB-GOV-001" in cap_explanations["faithfulness"]
    )
    assert case["reasons"]["answer_relevance"] == cap_explanations["answer_relevance"]
    assert case["reasons"]["faithfulness"] == cap_explanations["faithfulness"]
    assert "fully met" not in case["reasons"]["answer_relevance"].lower()
    assert "fully met" not in case["reasons"]["faithfulness"].lower()

    bundle = build_trace_bundle(result)
    published_reasons = {
        item["name"]: item["reason"] for item in bundle["trace_feedback.json"]["scores"]
    }
    assert published_reasons["answer_relevance"] == cap_explanations["answer_relevance"]
    assert published_reasons["faithfulness"] == cap_explanations["faithfulness"]


@pytest.mark.parametrize(
    ("audit_field", "audit_value"),
    [
        ("required_points_met", [-1]),
        ("required_points_met", [2]),
        ("required_points_met", [0, 0]),
        ("prohibited_claims_present", [1]),
        ("prohibited_claims_present", [0, 0]),
        ("non_authoritative_evidence_used", ["DOM-POL-001"]),
        ("non_authoritative_evidence_used", ["HB-GOV-001", "HB-GOV-001"]),
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
            judge_client=FakeCompletionClient([json.dumps(response)] * 2),
        )


def test_score_prompt_reports_redacted_judge_contract_shape(
    tmp_path: Path,
) -> None:
    public = write_contexts(tmp_path)
    response = json.loads(judge_response())
    response["reasoning"] = "PRIVATE JUDGE OUTPUT"

    with pytest.raises(ValueError) as raised:
        score_prompt(
            team_id="team-01",
            attempt=1,
            run_id="run-invalid-judge-shape",
            participant_prompt="Return JSON.",
            cases=make_cases(),
            public_directory=public,
            candidate_client=FakeCompletionClient([valid_answer()] * 50),
            judge_client=FakeCompletionClient([json.dumps(response)] * 2),
        )

    message = str(raised.value)
    assert "validation_locations=reasoning" in message
    assert "validation_types=extra_forbidden" in message
    assert "response_chars=" in message
    assert "response_sha256=" in message
    assert "PRIVATE JUDGE OUTPUT" not in message


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


def test_score_prompt_does_not_exceed_call_ceiling_for_contract_retry(
    tmp_path: Path,
) -> None:
    public = write_contexts(tmp_path)
    answer_client = FakeCompletionClient([valid_answer()] * 50)
    judge_client = FakeCompletionClient(["not-json"])

    with pytest.raises(ValueError, match="Judge response"):
        score_prompt(
            team_id="team-01",
            attempt=1,
            run_id="run-no-retry-budget",
            participant_prompt="Return JSON.",
            cases=make_cases(),
            public_directory=public,
            candidate_client=answer_client,
            judge_client=judge_client,
            max_calls=100,
        )

    assert len(answer_client.calls) == 1
    assert len(judge_client.calls) == 1
    assert MAX_RUN_CALLS == 105


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

    with pytest.raises(ValueError, match="1000000 token limit"):
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


def test_score_prompt_retries_invalid_judge_output_once_then_fails(
    tmp_path: Path,
) -> None:
    public = write_contexts(tmp_path)
    answer_client = FakeCompletionClient([valid_answer()] * 50)
    judge_client = FakeCompletionClient(["not-json", "still-not-json"])

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
    assert len(judge_client.calls) == 2
    assert judge_client.calls[0][0] != judge_client.calls[1][0]
    assert "compact replacement JSON" in judge_client.calls[1][0][0]["content"]


def test_score_prompt_recovers_from_one_invalid_judge_response(
    tmp_path: Path,
) -> None:
    public = write_contexts(tmp_path)
    judge_client = FakeCompletionClient(
        ["not-json", judge_response(), *([judge_response()] * 49)]
    )

    result = score_prompt(
        team_id="team-01",
        attempt=1,
        run_id="run-contract-retry",
        participant_prompt="Return JSON.",
        cases=make_cases(),
        public_directory=public,
        candidate_client=FakeCompletionClient([valid_answer()] * 50),
        judge_client=judge_client,
    )

    assert result["call_count"] == 101
    assert len(judge_client.calls) == 51
    first_case = result["discovery"]["cases"][0]
    assert first_case["usage"]["judge_attempts"] == 2
    assert first_case["usage"]["judge_prompt_tokens"] == 200
    assert first_case["usage"]["judge_completion_tokens"] == 40
    assert result["token_usage"]["judge"]["total_tokens"] == 6_120


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
            judge_client=FakeCompletionClient([json.dumps(response)] * 2),
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
