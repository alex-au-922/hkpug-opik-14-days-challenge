import importlib.util
import json
from pathlib import Path

import pytest

from hkpug_challenge import fireworks
from hkpug_challenge.scoring import MAX_RUN_CALLS, MAX_RUN_TOKENS


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIREWORKS_MODEL = "accounts/fireworks/models/deepseek-v4-flash"
JUDGE_MODEL = "accounts/fireworks/models/qwen3p7-plus"


def test_tournament_models_have_distinct_supported_fireworks_defaults() -> None:
    assert fireworks.FIREWORKS_MODEL == FIREWORKS_MODEL
    assert getattr(fireworks, "JUDGE_MODEL", None) == JUDGE_MODEL
    assert JUDGE_MODEL != FIREWORKS_MODEL


def test_scoring_uses_the_documented_run_token_budget() -> None:
    assert MAX_RUN_TOKENS == 1_000_000
    assert MAX_RUN_CALLS == 105


def test_trusted_scoring_passes_repository_model_variables_to_the_scorer() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/trusted-score.yml").read_text(
        encoding="utf-8"
    )
    score_step = workflow.split("- name: Score fixed evaluation bank", maxsplit=1)[1]
    score_step = score_step.split("- name: Encrypt submission feedback", maxsplit=1)[0]

    assert "FIREWORKS_MODEL: ${{ vars.FIREWORKS_MODEL }}" in score_step
    assert "JUDGE_MODEL: ${{ vars.JUDGE_MODEL }}" in score_step
    assert "FIREWORKS_JUDGE_MODEL" not in score_step
    assert (
        'test "$FIREWORKS_MODEL" = "accounts/fireworks/models/deepseek-v4-flash"'
        in score_step
    )
    assert (
        'test "$JUDGE_MODEL" = "accounts/fireworks/models/qwen3p7-plus"' in score_step
    )


def test_score_script_requires_explicit_model_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_score_submission_module()
    monkeypatch.setenv("FIREWORKS_MODEL", FIREWORKS_MODEL)
    monkeypatch.delenv("JUDGE_MODEL", raising=False)

    with pytest.raises(ValueError, match="JUDGE_MODEL"):
        module._scoring_models()


def test_score_script_loads_exact_model_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_score_submission_module()
    monkeypatch.setenv("FIREWORKS_MODEL", FIREWORKS_MODEL)
    monkeypatch.setenv("JUDGE_MODEL", JUDGE_MODEL)

    assert module._scoring_models() == (FIREWORKS_MODEL, JUDGE_MODEL)


def test_public_summary_excludes_private_scoring_details() -> None:
    module = load_score_submission_module()
    result = {
        "team_id": "team-01",
        "attempt": 1,
        "run_id": "run-001",
        "model": FIREWORKS_MODEL,
        "judge_model": "PRIVATE-JUDGE-METADATA",
        "prompt_sha256": "a" * 64,
        "overall_score": 50.0,
        "discovery": {
            "case_count": 40,
            "criteria": {"answer_relevance": 10.0},
            "score": 50.0,
            "cases": [
                {
                    "input": "PRIVATE-DISCOVERY-CONTEXT",
                    "reasons": "PRIVATE-JUDGE-REASON",
                }
            ],
        },
        "holdout": {
            "case_count": 10,
            "criteria": {"answer_relevance": 10.0},
            "score": 50.0,
            "cases": [{"input": "PRIVATE-HOLDOUT-CONTEXT"}],
        },
        "token_usage": {
            "candidate": {
                "prompt_tokens": 1000,
                "completion_tokens": 200,
                "total_tokens": 1200,
            },
            "judge": {
                "prompt_tokens": 800,
                "completion_tokens": 100,
                "total_tokens": 900,
            },
            "total": {
                "prompt_tokens": 1800,
                "completion_tokens": 300,
                "total_tokens": 2100,
            },
        },
        "call_count": 100,
        "started_at": "2026-07-13T00:00:00.000Z",
        "completed_at": "2026-07-13T00:01:00.000Z",
    }

    summary = module._public_summary(result)

    assert set(summary) == {
        "schema_version",
        "team_id",
        "attempt",
        "run_id",
        "model",
        "prompt_sha256",
        "overall_score",
        "discovery",
        "holdout",
        "token_usage",
        "call_count",
        "started_at",
        "completed_at",
    }
    assert set(summary["discovery"]) == {"case_count", "criteria", "score"}
    assert set(summary["holdout"]) == {"case_count", "criteria", "score"}
    assert summary["token_usage"] == result["token_usage"]
    serialized = json.dumps(summary)
    assert "PRIVATE-JUDGE-METADATA" not in serialized
    assert "PRIVATE-DISCOVERY-CONTEXT" not in serialized
    assert "PRIVATE-HOLDOUT-CONTEXT" not in serialized
    assert "PRIVATE-JUDGE-REASON" not in serialized


@pytest.mark.parametrize(
    ("token_usage", "message"),
    [
        pytest.param(None, "token_usage", id="missing-token-usage"),
        pytest.param(
            {
                "candidate": {
                    "prompt_tokens": 1,
                    "completion_tokens": 2,
                    "total_tokens": 3,
                },
                "judge": {
                    "prompt_tokens": 4,
                    "completion_tokens": 5,
                    "total_tokens": 9,
                },
            },
            "total",
            id="missing-total-bucket",
        ),
        pytest.param(
            {
                "candidate": {
                    "prompt_tokens": 1,
                    "completion_tokens": 2,
                    "total_tokens": 3,
                },
                "judge": {
                    "prompt_tokens": 4,
                    "completion_tokens": 5,
                    "total_tokens": 9,
                },
                "total": {
                    "prompt_tokens": 5,
                    "completion_tokens": True,
                    "total_tokens": 12,
                },
            },
            "completion_tokens",
            id="bool-token-count",
        ),
    ],
)
def test_public_summary_requires_valid_aggregate_token_usage(
    token_usage: object,
    message: str,
) -> None:
    module = load_score_submission_module()
    result: dict[str, object] = {
        "team_id": "team-01",
        "attempt": 1,
        "run_id": "run-001",
        "model": FIREWORKS_MODEL,
        "prompt_sha256": "a" * 64,
        "overall_score": 50.0,
        "discovery": {
            "case_count": 40,
            "criteria": {"answer_relevance": 10.0},
            "score": 50.0,
            "cases": [],
        },
        "holdout": {
            "case_count": 10,
            "criteria": {"answer_relevance": 10.0},
            "score": 50.0,
        },
        "call_count": 100,
        "started_at": "2026-07-13T00:00:00.000Z",
        "completed_at": "2026-07-13T00:01:00.000Z",
    }
    if token_usage is not None:
        result["token_usage"] = token_usage

    with pytest.raises(ValueError, match=message):
        module._public_summary(result)


def load_score_submission_module():
    script_path = REPOSITORY_ROOT / ".github/tournament/scripts/score_submission.py"
    spec = importlib.util.spec_from_file_location(
        "score_submission_script", script_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
