from __future__ import annotations

from typing import cast


CRITERIA = (
    ("json_schema", "JSON schema", 10.0),
    ("citation_validity", "Citation validity", 10.0),
    ("evidence_coverage", "Evidence coverage", 10.0),
    ("escalation", "Escalation", 10.0),
    ("answer_relevance", "Answer relevance", 20.0),
    ("instruction_following", "Instruction following", 15.0),
    ("faithfulness", "Faithfulness", 25.0),
)


def render_action_summary(summary: dict[str, object]) -> str:
    discovery = _required_object(summary, "discovery")
    holdout = _required_object(summary, "holdout")
    discovery_criteria = _required_object(discovery, "criteria")
    holdout_criteria = _required_object(holdout, "criteria")
    usage = _required_object(summary, "token_usage")
    candidate_usage = _required_object(usage, "candidate")
    judge_usage = _required_object(usage, "judge")
    total_usage = _required_object(usage, "total")

    lines = [
        "# Tournament scoring complete",
        "",
        f"**Team:** `{_required_text(summary, 'team_id')}`  ",
        f"**Attempt:** {_required_int(summary, 'attempt')}/8  ",
        f"**Overall score:** {_required_number(summary, 'overall_score'):.2f}/100",
        "",
        "## Weighted result",
        "",
        "| Partition | Weight | Cases | Score |",
        "| --- | ---: | ---: | ---: |",
        (
            "| Discovery | 75% | "
            f"{_required_int(discovery, 'case_count')} | "
            f"{_required_number(discovery, 'score'):.2f} |"
        ),
        (
            "| Hidden holdout | 25% | "
            f"{_required_int(holdout, 'case_count')} | "
            f"{_required_number(holdout, 'score'):.2f} |"
        ),
        "",
        "`overall = discovery x 0.75 + holdout x 0.25`",
        "",
        "## Criterion contributions",
        "",
        "| Criterion | Maximum | Discovery | Hidden holdout |",
        "| --- | ---: | ---: | ---: |",
    ]
    lines.extend(
        (
            f"| {label} | {maximum:.0f} | "
            f"{_required_number(discovery_criteria, key):.2f} | "
            f"{_required_number(holdout_criteria, key):.2f} |"
        )
        for key, label, maximum in CRITERIA
    )
    lines.extend(
        [
            "",
            "Each value is the average point contribution for that partition. "
            "Missing required points can cap answer relevance; prohibited claims or "
            "unsafe evidence can cap faithfulness.",
            "",
            "Case-level scores and reasons for all 40 discovery cases are in the "
            "team-encrypted submission feedback and appear after import into Opik. "
            "The 10 holdout cases remain aggregate-only.",
            "",
            "## Model usage",
            "",
            "| Stage | Prompt tokens | Completion tokens | Total |",
            "| --- | ---: | ---: | ---: |",
            _usage_row("Candidate", candidate_usage),
            _usage_row("Judge", judge_usage),
            _usage_row("Total", total_usage),
            "",
            f"**API calls:** {_required_int(summary, 'call_count')}",
            "",
        ]
    )
    return "\n".join(lines)


def _usage_row(label: str, usage: dict[str, object]) -> str:
    return (
        f"| {label} | {_required_int(usage, 'prompt_tokens'):,} | "
        f"{_required_int(usage, 'completion_tokens'):,} | "
        f"{_required_int(usage, 'total_tokens'):,} |"
    )


def _required_object(value: dict[str, object], key: str) -> dict[str, object]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise ValueError(f"Scoring summary field {key} must be an object.")
    return cast(dict[str, object], item)


def _required_text(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"Scoring summary field {key} must be text.")
    return item


def _required_int(value: dict[str, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"Scoring summary field {key} must be an integer.")
    return item


def _required_number(value: dict[str, object], key: str) -> float:
    item = value.get(key)
    if not isinstance(item, (int, float)) or isinstance(item, bool):
        raise ValueError(f"Scoring summary field {key} must be numeric.")
    return float(item)
