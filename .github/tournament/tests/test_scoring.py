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
from hkpug_challenge.fireworks import Completion
from hkpug_challenge.models import Message
from hkpug_challenge.scoring import score_prompt


class FakeCompletionClient:
    def __init__(self, responses: Sequence[str]) -> None:
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
        return Completion(
            content=next(self._responses),
            prompt_tokens=100,
            completion_tokens=20,
        )


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
            required_points=("State Alpha.",),
            prohibited_claims=("Claim Beta.",),
            non_authoritative_evidence=(),
        ),
    )


def judge_response(
    relevance: int = 80, instruction: int = 90, faithfulness: int = 70
) -> str:
    return json.dumps(
        {
            "answer_relevance": relevance,
            "instruction_following": instruction,
            "faithfulness": faithfulness,
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


def test_score_prompt_returns_discovery_detail_and_aggregate_holdout(
    tmp_path: Path,
) -> None:
    public = write_contexts(tmp_path)
    cases = (make_case("DISC-01", "discovery"), make_case("HOLD-01", "holdout"))
    client = FakeCompletionClient(
        [valid_answer(), judge_response(), valid_answer(), judge_response()]
    )

    result = score_prompt(
        team_id="team-01",
        attempt=1,
        run_id="run-001",
        participant_prompt="Use evidence and return strict JSON.",
        cases=cases,
        public_directory=public,
        client=client,
    )

    assert len(client.calls) == 4
    assert [max_tokens for _messages, max_tokens, _format in client.calls] == [
        256,
        384,
        256,
        384,
    ]
    assert client.calls[0][2] is None
    assert client.calls[1][2] is not None
    assert client.calls[2][2] is None
    assert client.calls[3][2] is not None
    assert result["overall_score"] == 87.0
    assert result["discovery"]["score"] == 87.0
    assert result["holdout"]["score"] == 87.0
    assert len(result["discovery"]["cases"]) == 1
    assert "cases" not in result["holdout"]
    assert result["call_count"] == 4
    serialized = json.dumps(result)
    assert "Use evidence and return strict JSON" not in serialized
    assert "The approved outcome is Alpha." in serialized
    assert "HOLD-01" not in serialized
    assert "reference" not in serialized
    assert "rubric" not in serialized
    assert "participant_prompt" in client.calls[0][0][-1]["content"]


def test_score_prompt_reports_case_progress_without_case_details(
    tmp_path: Path,
) -> None:
    public = write_contexts(tmp_path)
    client = FakeCompletionClient(
        [valid_answer(), judge_response(), valid_answer(), judge_response()]
    )
    progress: list[tuple[int, int]] = []

    score_prompt(
        team_id="team-01",
        attempt=1,
        run_id="run-progress",
        participant_prompt="Return JSON.",
        cases=(make_case("DISC-01", "discovery"), make_case("HOLD-01", "holdout")),
        public_directory=public,
        client=client,
        on_case_start=lambda current, total: progress.append((current, total)),
    )

    assert progress == [(1, 2), (2, 2)]


def test_score_prompt_applies_partial_deterministic_scores(tmp_path: Path) -> None:
    public = write_contexts(tmp_path)
    partial_answer = json.dumps(
        {
            "answer": "Alpha.",
            "citations": ["DOM-POL-001"],
            "escalate": False,
        }
    )
    client = FakeCompletionClient(
        [
            partial_answer,
            judge_response(50, 100, 50),
            partial_answer,
            judge_response(50, 100, 50),
        ]
    )

    result = score_prompt(
        team_id="team-01",
        attempt=2,
        run_id="run-002",
        participant_prompt="Return JSON.",
        cases=(make_case("DISC-01", "discovery"), make_case("HOLD-01", "holdout")),
        public_directory=public,
        client=client,
    )

    assert result["overall_score"] == 72.5
    assert result["discovery"]["criteria"]["evidence_coverage"] == 5.0


def test_score_prompt_enforces_call_ceiling_before_model_calls(tmp_path: Path) -> None:
    public = write_contexts(tmp_path)
    client = FakeCompletionClient([])

    with pytest.raises(ValueError, match="call limit"):
        score_prompt(
            team_id="team-01",
            attempt=1,
            run_id="run-003",
            participant_prompt="Return JSON.",
            cases=(make_case("DISC-01", "discovery"), make_case("HOLD-01", "holdout")),
            public_directory=public,
            client=client,
            max_calls=3,
        )

    assert client.calls == []


def test_score_prompt_does_not_retry_invalid_judge_output(tmp_path: Path) -> None:
    public = write_contexts(tmp_path)
    client = FakeCompletionClient([valid_answer(), "not-json"])

    with pytest.raises(ValueError, match="Judge response"):
        score_prompt(
            team_id="team-01",
            attempt=1,
            run_id="run-004",
            participant_prompt="Return JSON.",
            cases=(make_case("DISC-01", "discovery"),),
            public_directory=public,
            client=client,
        )

    assert len(client.calls) == 2
