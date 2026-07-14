from __future__ import annotations

from hkpug_challenge.action_summary import CRITERIA, render_action_summary


def test_action_summary_explains_score_without_hidden_case_details() -> None:
    criteria = {key: maximum * 0.8 for key, _, maximum in CRITERIA}
    summary: dict[str, object] = {
        "team_id": "team-01",
        "attempt": 3,
        "overall_score": 80.0,
        "call_count": 101,
        "discovery": {
            "case_count": 40,
            "score": 80.0,
            "criteria": criteria,
        },
        "holdout": {
            "case_count": 10,
            "score": 80.0,
            "criteria": criteria,
            "cases": [
                {
                    "question": "PRIVATE HOLDOUT QUESTION",
                    "output": "PRIVATE HOLDOUT OUTPUT",
                }
            ],
        },
        "token_usage": {
            "candidate": {
                "prompt_tokens": 100_000,
                "completion_tokens": 10_000,
                "total_tokens": 110_000,
            },
            "judge": {
                "prompt_tokens": 200_000,
                "completion_tokens": 20_000,
                "total_tokens": 220_000,
            },
            "total": {
                "prompt_tokens": 300_000,
                "completion_tokens": 30_000,
                "total_tokens": 330_000,
            },
        },
    }

    rendered = render_action_summary(summary)

    assert "**Overall score:** 80.00/100" in rendered
    assert "`overall = discovery x 0.75 + holdout x 0.25`" in rendered
    assert "| Answer relevance | 20 | 16.00 | 16.00 |" in rendered
    assert "all 40 discovery cases" in rendered
    assert "10 holdout cases remain aggregate-only" in rendered
    assert "**API calls:** 101" in rendered
    assert "PRIVATE HOLDOUT" not in rendered
