from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from .fireworks import FIREWORKS_MODEL, CompletionClient
from .messages import render_messages
from .models import Message, PublicCase


Partition = Literal["discovery", "holdout"]
JUDGE_WEIGHTS = {
    "answer_relevance": 0.20,
    "instruction_following": 0.15,
    "faithfulness": 0.25,
}
STRUCTURE_CRITERIA = (
    "json_schema",
    "answer_contract",
    "citation_contract",
    "escalation_contract",
)


@dataclass(frozen=True)
class PlaygroundCase:
    case: PublicCase
    partition: Partition


class _JudgeReasons(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    answer_relevance: str
    instruction_following: str
    faithfulness: str


class _JudgePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_relevance: StrictInt = Field(ge=0, le=100)
    instruction_following: StrictInt = Field(ge=0, le=100)
    faithfulness: StrictInt = Field(ge=0, le=100)
    reasons: _JudgeReasons


def run_playground(
    *,
    system_prompt: str,
    cases: tuple[PlaygroundCase, ...],
    client: CompletionClient,
) -> dict[str, Any]:
    prompt = system_prompt.strip()
    if not prompt:
        raise ValueError("System prompt must not be empty.")
    partition_counts = Counter(item.partition for item in cases)
    if partition_counts["discovery"] < 1 or partition_counts["holdout"] < 1:
        raise ValueError("Playground requires discovery and holdout cases.")

    case_results = [
        _run_case(item=item, system_prompt=prompt, client=client) for item in cases
    ]
    discovery_results = [
        result for result in case_results if result["partition"] == "discovery"
    ]
    holdout_results = [
        result for result in case_results if result["partition"] == "holdout"
    ]
    discovery = _aggregate_partition(discovery_results)
    discovery["cases"] = [
        {key: value for key, value in result.items() if key != "partition"}
        for result in discovery_results
    ]
    holdout = _aggregate_partition(holdout_results)
    overall_score = round(
        float(discovery["score"]) * 0.75 + float(holdout["score"]) * 0.25,
        2,
    )

    return {
        "schema_version": 1,
        "model": FIREWORKS_MODEL,
        "prompt_sha256": sha256(prompt.encode("utf-8")).hexdigest(),
        "weights": {"discovery": 0.75, "holdout": 0.25},
        "discovery": discovery,
        "holdout": holdout,
        "overall_score": overall_score,
        "call_count": len(cases) * 2,
    }


def _run_case(
    *, item: PlaygroundCase, system_prompt: str, client: CompletionClient
) -> dict[str, Any]:
    answer_completion = client.complete(
        render_messages(item.case, system_prompt), max_tokens=256
    )
    structure_scores = _score_structure(item.case, answer_completion.content)
    judge_completion = client.complete(
        _judge_messages(item.case, answer_completion.content), max_tokens=192
    )
    judge = _parse_judge(judge_completion.content)
    criteria: dict[str, float] = dict(structure_scores)
    for name, weight in JUDGE_WEIGHTS.items():
        criteria[name] = round(float(getattr(judge, name)) * weight, 2)

    return {
        "partition": item.partition,
        "case_id": item.case.id,
        "input": {
            "question": item.case.question,
            "context": item.case.context,
        },
        "output": answer_completion.content,
        "criteria": criteria,
        "score": round(sum(criteria.values()), 2),
        "reasons": judge.reasons.model_dump(),
        "usage": {
            "answer_prompt_tokens": answer_completion.prompt_tokens,
            "answer_completion_tokens": answer_completion.completion_tokens,
            "judge_prompt_tokens": judge_completion.prompt_tokens,
            "judge_completion_tokens": judge_completion.completion_tokens,
        },
    }


def _score_structure(case: PublicCase, response: str) -> dict[str, float]:
    scores = {name: 0.0 for name in STRUCTURE_CRITERIA}
    try:
        payload_value = cast(object, json.loads(response))
    except json.JSONDecodeError:
        return scores
    if not isinstance(payload_value, dict):
        return scores
    payload = cast(dict[str, object], payload_value)

    if set(payload) == {"answer", "citations", "escalate"}:
        scores["json_schema"] = 10.0
    answer = payload.get("answer")
    if isinstance(answer, str) and answer.strip() and len(answer.split()) <= 100:
        scores["answer_contract"] = 10.0
    citations_value = payload.get("citations")
    if isinstance(citations_value, list):
        citations = cast(list[object], citations_value)
        if citations and all(isinstance(value, str) and value for value in citations):
            citation_strings = cast(list[str], citations)
            if len(citation_strings) == len(set(citation_strings)) and set(
                citation_strings
            ).issubset(case.evidence_ids):
                scores["citation_contract"] = 10.0
    if isinstance(payload.get("escalate"), bool):
        scores["escalation_contract"] = 10.0
    return scores


def _judge_messages(case: PublicCase, answer: str) -> tuple[Message, ...]:
    judge_input = json.dumps(
        {
            "question": case.question,
            "context": case.context,
            "candidate_answer": answer,
        },
        ensure_ascii=False,
    )
    return (
        {
            "role": "system",
            "content": (
                "Evaluate the candidate support answer using only the supplied context. "
                "Return one JSON object with integer scores from 0 to 100 for "
                "answer_relevance, instruction_following, and faithfulness, plus a "
                "reasons object containing one short reason for each score."
            ),
        },
        {"role": "user", "content": judge_input},
    )


def _parse_judge(response: str) -> _JudgePayload:
    try:
        payload = cast(object, json.loads(response))
        return _JudgePayload.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError("Judge response did not match the scoring contract.") from exc


def _aggregate_partition(results: list[dict[str, Any]]) -> dict[str, Any]:
    case_count = len(results)
    criteria_names = (*STRUCTURE_CRITERIA, *JUDGE_WEIGHTS)
    criteria = {
        name: round(
            sum(float(result["criteria"][name]) for result in results) / case_count,
            2,
        )
        for name in criteria_names
    }
    return {
        "case_count": case_count,
        "criteria": criteria,
        "score": round(sum(criteria.values()), 2),
    }
