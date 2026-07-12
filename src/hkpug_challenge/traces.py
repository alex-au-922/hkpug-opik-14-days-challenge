from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5


CRITERION_MAX = {
    "json_schema": 10.0,
    "citation_validity": 10.0,
    "evidence_coverage": 10.0,
    "escalation": 10.0,
    "answer_relevance": 20.0,
    "instruction_following": 15.0,
    "faithfulness": 25.0,
}
BUNDLE_FILENAMES = (
    "run.json",
    "trace_payload.json",
    "span_payload.json",
    "trace_feedback.json",
    "span_feedback.json",
)


def build_trace_bundle(
    scoring_result: dict[str, object],
) -> dict[str, dict[str, Any]]:
    team_id = _required_text(scoring_result, "team_id")
    run_id = _required_text(scoring_result, "run_id")
    project_name = f"hkpug-{team_id}-{run_id}"
    discovery = _required_object(scoring_result, "discovery")
    holdout = _aggregate_only(_required_object(scoring_result, "holdout"))
    discovery_cases = _required_list(discovery, "cases")

    traces: list[dict[str, Any]] = []
    spans: list[dict[str, Any]] = []
    trace_scores: list[dict[str, Any]] = []
    span_scores: list[dict[str, Any]] = []
    for case_value in discovery_cases:
        if not isinstance(case_value, dict):
            raise ValueError("Discovery cases must be JSON objects.")
        case = cast(dict[str, object], case_value)
        case_id = _required_text(case, "case_id")
        trace_id = _stable_id(team_id, run_id, case_id, "trace")
        answer_span_id = _stable_id(team_id, run_id, case_id, "span/answer")
        judge_span_id = _stable_id(team_id, run_id, case_id, "span/judge")
        case_input = _required_object(case, "input")
        output_text = _required_text(case, "output")
        output = _decode_output(output_text)
        criteria = _required_object(case, "criteria")
        reasons = _required_object(case, "reasons")
        usage = _required_object(case, "usage")
        timing = _required_object(case, "timing")
        metadata = {
            "partition": "discovery",
            "case_id": case_id,
            "domain": _required_text(case, "domain"),
            "difficulty": _required_text(case, "difficulty"),
            "attempt": _required_int(scoring_result, "attempt"),
            "model": _required_text(scoring_result, "model"),
        }
        traces.append(
            {
                "id": trace_id,
                "project_name": project_name,
                "name": f"{case_id} support evaluation",
                "start_time": _required_text(timing, "answer_started_at"),
                "end_time": _required_text(timing, "judge_completed_at"),
                "input": case_input,
                "output": output,
                "metadata": metadata,
                "source": "sdk",
            }
        )
        spans.extend(
            [
                {
                    "id": answer_span_id,
                    "trace_id": trace_id,
                    "project_name": project_name,
                    "name": "model.answer",
                    "type": "llm",
                    "start_time": _required_text(timing, "answer_started_at"),
                    "end_time": _required_text(timing, "answer_completed_at"),
                    "input": case_input,
                    "output": output,
                    "metadata": metadata
                    | {
                        "prompt_tokens": _required_int(usage, "answer_prompt_tokens"),
                        "completion_tokens": _required_int(
                            usage, "answer_completion_tokens"
                        ),
                    },
                    "source": "sdk",
                },
                {
                    "id": judge_span_id,
                    "trace_id": trace_id,
                    "parent_span_id": answer_span_id,
                    "project_name": project_name,
                    "name": "evaluation.judge",
                    "type": "llm",
                    "start_time": _required_text(timing, "judge_started_at"),
                    "end_time": _required_text(timing, "judge_completed_at"),
                    "input": {
                        "candidate_answer": output,
                        "criteria": list(CRITERION_MAX),
                    },
                    "output": {"criteria": criteria, "reasons": reasons},
                    "metadata": metadata
                    | {
                        "prompt_tokens": _required_int(usage, "judge_prompt_tokens"),
                        "completion_tokens": _required_int(
                            usage, "judge_completion_tokens"
                        ),
                    },
                    "source": "sdk",
                },
            ]
        )
        for criterion, maximum in CRITERION_MAX.items():
            contribution = _required_number(criteria, criterion)
            reason = _criterion_reason(criterion, contribution, maximum, reasons)
            value = round(contribution / maximum, 4)
            trace_scores.append(
                {
                    "id": trace_id,
                    "project_name": project_name,
                    "name": criterion,
                    "value": value,
                    "reason": reason,
                    "source": "sdk",
                }
            )
            span_scores.append(
                {
                    "id": answer_span_id,
                    "project_name": project_name,
                    "name": criterion,
                    "value": value,
                    "reason": reason,
                    "source": "sdk",
                }
            )

    run = {
        "schema_version": 1,
        "bundle_partition": "discovery",
        "team_id": team_id,
        "run_id": run_id,
        "attempt": _required_int(scoring_result, "attempt"),
        "project_name": project_name,
        "model": _required_text(scoring_result, "model"),
        "prompt_sha256": _required_text(scoring_result, "prompt_sha256"),
        "overall_score": _required_number(scoring_result, "overall_score"),
        "weights": _required_object(scoring_result, "weights"),
        "discovery": _aggregate_only(discovery),
        "holdout": holdout,
        "started_at": _required_text(scoring_result, "started_at"),
        "completed_at": _required_text(scoring_result, "completed_at"),
    }
    return {
        "run.json": run,
        "trace_payload.json": {"traces": traces},
        "span_payload.json": {"spans": spans},
        "trace_feedback.json": {"scores": trace_scores},
        "span_feedback.json": {"scores": span_scores},
    }


def write_trace_bundle(scoring_result: dict[str, object], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    bundle = build_trace_bundle(scoring_result)
    for filename in BUNDLE_FILENAMES:
        path = output / filename
        path.write_text(
            json.dumps(bundle[filename], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if os.name != "nt":
            path.chmod(0o600)


def _stable_id(team_id: str, run_id: str, case_id: str, entity: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"hkpug/{team_id}/{run_id}/{case_id}/{entity}"))


def _decode_output(value: str) -> object:
    try:
        return cast(object, json.loads(value))
    except json.JSONDecodeError:
        return value


def _criterion_reason(
    criterion: str,
    contribution: float,
    maximum: float,
    reasons: dict[str, object],
) -> str:
    reason = reasons.get(criterion)
    if isinstance(reason, str) and reason:
        return reason
    return f"Deterministic contract contribution: {contribution:g}/{maximum:g}."


def _aggregate_only(value: dict[str, object]) -> dict[str, object]:
    return {
        "case_count": _required_int(value, "case_count"),
        "criteria": _required_object(value, "criteria"),
        "score": _required_number(value, "score"),
    }


def _required_object(value: dict[str, object], key: str) -> dict[str, object]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise ValueError(f"Scoring result field {key} must be an object.")
    return cast(dict[str, object], item)


def _required_list(value: dict[str, object], key: str) -> list[object]:
    item = value.get(key)
    if not isinstance(item, list):
        raise ValueError(f"Scoring result field {key} must be a list.")
    return cast(list[object], item)


def _required_text(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"Scoring result field {key} must be non-empty text.")
    return item


def _required_int(value: dict[str, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"Scoring result field {key} must be an integer.")
    return item


def _required_number(value: dict[str, object], key: str) -> float:
    item = value.get(key)
    if not isinstance(item, (int, float)) or isinstance(item, bool):
        raise ValueError(f"Scoring result field {key} must be numeric.")
    return float(item)
