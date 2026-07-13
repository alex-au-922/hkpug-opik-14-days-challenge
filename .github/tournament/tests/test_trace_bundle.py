from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from hkpug_challenge.traces import build_trace_bundle, write_trace_bundle


def scoring_result() -> dict[str, object]:
    return {
        "schema_version": 1,
        "team_id": "team-01",
        "attempt": 1,
        "run_id": "run-001",
        "model": "accounts/fireworks/models/deepseek-v4-flash",
        "judge_model": "accounts/fireworks/models/qwen3p7-plus",
        "prompt_sha256": "a" * 64,
        "weights": {"discovery": 0.75, "holdout": 0.25},
        "overall_score": 87.0,
        "call_count": 4,
        "token_usage": {
            "candidate": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            },
            "judge": {
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "total_tokens": 150,
            },
            "total": {
                "prompt_tokens": 220,
                "completion_tokens": 50,
                "total_tokens": 270,
            },
        },
        "started_at": "2026-07-12T00:00:00.000Z",
        "completed_at": "2026-07-12T00:00:02.000Z",
        "discovery": {
            "case_count": 1,
            "score": 87.0,
            "criteria": {
                "json_schema": 10.0,
                "citation_validity": 10.0,
                "evidence_coverage": 10.0,
                "escalation": 10.0,
                "answer_relevance": 16.0,
                "instruction_following": 13.5,
                "faithfulness": 17.5,
            },
            "cases": [
                {
                    "case_id": "DISC-01",
                    "domain": "refunds",
                    "difficulty": "standard",
                    "input": {
                        "question": "What outcome is supported?",
                        "context": "## [REF-POL-001]\nUse Alpha.",
                    },
                    "output": (
                        '{"answer":"Alpha.","citations":["REF-POL-001"],'
                        '"escalate":false}'
                    ),
                    "criteria": {
                        "json_schema": 10.0,
                        "citation_validity": 10.0,
                        "evidence_coverage": 10.0,
                        "escalation": 10.0,
                        "answer_relevance": 16.0,
                        "instruction_following": 13.5,
                        "faithfulness": 17.5,
                    },
                    "score": 87.0,
                    "reasons": {
                        "answer_relevance": "Answers the requested decision.",
                        "instruction_following": "Follows the JSON contract.",
                        "faithfulness": "Claims follow the supplied evidence.",
                    },
                    "usage": {
                        "answer_prompt_tokens": 100,
                        "answer_completion_tokens": 20,
                        "judge_prompt_tokens": 120,
                        "judge_completion_tokens": 30,
                    },
                    "timing": {
                        "answer_started_at": "2026-07-12T00:00:00.000Z",
                        "answer_completed_at": "2026-07-12T00:00:00.800Z",
                        "judge_started_at": "2026-07-12T00:00:00.900Z",
                        "judge_completed_at": "2026-07-12T00:00:01.800Z",
                    },
                }
            ],
        },
        "holdout": {
            "case_count": 1,
            "score": 87.0,
            "criteria": {
                "json_schema": 10.0,
                "citation_validity": 10.0,
                "evidence_coverage": 10.0,
                "escalation": 10.0,
                "answer_relevance": 16.0,
                "instruction_following": 13.5,
                "faithfulness": 17.5,
            },
        },
    }


def test_trace_bundle_has_answer_and_judge_spans_without_holdout_details() -> None:
    first = build_trace_bundle(scoring_result())
    second = build_trace_bundle(scoring_result())

    assert first == second
    assert first["run.json"]["bundle_partition"] == "discovery"
    assert len(first["trace_payload.json"]["traces"]) == 1
    assert len(first["span_payload.json"]["spans"]) == 2
    assert {span["name"] for span in first["span_payload.json"]["spans"]} == {
        "model.answer",
        "evaluation.judge",
    }
    spans = {span["name"]: span for span in first["span_payload.json"]["spans"]}
    assert spans["model.answer"]["metadata"]["model"] == (
        "accounts/fireworks/models/deepseek-v4-flash"
    )
    assert spans["evaluation.judge"]["metadata"]["model"] == (
        "accounts/fireworks/models/qwen3p7-plus"
    )
    assert first["run.json"]["judge_model"] == (
        "accounts/fireworks/models/qwen3p7-plus"
    )
    assert first["run.json"]["token_usage"] == scoring_result()["token_usage"]
    assert first["trace_payload.json"]["traces"][0]["metadata"]["model"] == (
        "accounts/fireworks/models/deepseek-v4-flash"
    )
    for item in (
        *first["trace_payload.json"]["traces"],
        *first["span_payload.json"]["spans"],
    ):
        UUID(item["id"])
        assert item["metadata"]["partition"] == "discovery"
    serialized = json.dumps(first)
    assert "holdout question" not in serialized
    assert "HOLD-01" not in serialized
    assert "participant_prompt" not in serialized
    assert "reference" not in serialized
    assert first["run.json"]["holdout"] == scoring_result()["holdout"]


def test_trace_bundle_requires_valid_aggregate_token_usage() -> None:
    payload = scoring_result()
    del payload["token_usage"]

    with pytest.raises(ValueError, match="token_usage"):
        build_trace_bundle(payload)


def test_write_trace_bundle_creates_only_replay_files(tmp_path: Path) -> None:
    write_trace_bundle(scoring_result(), tmp_path)

    assert {path.name for path in tmp_path.iterdir()} == {
        "run.json",
        "trace_payload.json",
        "span_payload.json",
        "trace_feedback.json",
        "span_feedback.json",
    }
    assert all(path.stat().st_mode & 0o077 == 0 for path in tmp_path.iterdir())
