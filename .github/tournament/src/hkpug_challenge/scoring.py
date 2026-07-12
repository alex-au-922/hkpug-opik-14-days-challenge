from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from .dataset import EVIDENCE_ID_PATTERN
from .evaluation_bank import EvaluationCase
from .fireworks import FIREWORKS_MODEL, CompletionClient
from .models import Message
from .playground import FIXED_SYSTEM_PROMPT


DISCOVERY_WEIGHT = 0.75
HOLDOUT_WEIGHT = 0.25
JUDGE_WEIGHTS = {
    "answer_relevance": 0.20,
    "instruction_following": 0.15,
    "faithfulness": 0.25,
}
DETERMINISTIC_CRITERIA = (
    "json_schema",
    "citation_validity",
    "evidence_coverage",
    "escalation",
)


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


def score_prompt(
    *,
    team_id: str,
    attempt: int,
    run_id: str,
    participant_prompt: str,
    cases: tuple[EvaluationCase, ...],
    public_directory: Path,
    client: CompletionClient,
    max_calls: int = 100,
) -> dict[str, Any]:
    prompt = participant_prompt.strip()
    if not prompt:
        raise ValueError("Participant prompt must not be empty.")
    if attempt < 1:
        raise ValueError("Attempt must be positive.")
    required_calls = len(cases) * 2
    if required_calls > max_calls:
        raise ValueError(
            f"Scoring requires {required_calls} calls, above the {max_calls} call limit."
        )

    started_at = _timestamp()
    results = [
        _score_case(
            case=case,
            participant_prompt=prompt,
            public_directory=public_directory,
            client=client,
        )
        for case in cases
    ]
    discovery_results = [
        result for result in results if result["partition"] == "discovery"
    ]
    holdout_results = [result for result in results if result["partition"] == "holdout"]
    discovery = _aggregate(discovery_results)
    discovery["cases"] = [
        {key: value for key, value in result.items() if key != "partition"}
        for result in discovery_results
    ]
    holdout = _aggregate(holdout_results)

    overall_score = round(
        float(discovery["score"]) * DISCOVERY_WEIGHT
        + float(holdout["score"]) * HOLDOUT_WEIGHT,
        2,
    )
    return {
        "schema_version": 1,
        "team_id": team_id,
        "attempt": attempt,
        "run_id": run_id,
        "model": FIREWORKS_MODEL,
        "prompt_sha256": sha256(prompt.encode("utf-8")).hexdigest(),
        "weights": {
            "discovery": DISCOVERY_WEIGHT,
            "holdout": HOLDOUT_WEIGHT,
        },
        "discovery": discovery,
        "holdout": holdout,
        "overall_score": overall_score,
        "call_count": required_calls,
        "started_at": started_at,
        "completed_at": _timestamp(),
    }


def _score_case(
    *,
    case: EvaluationCase,
    participant_prompt: str,
    public_directory: Path,
    client: CompletionClient,
) -> dict[str, Any]:
    context, evidence_ids = _load_context(
        public_directory=public_directory,
        context_files=case.context_files,
    )
    answer_started_at = _timestamp()
    answer_completion = client.complete(
        _answer_messages(
            question=case.question,
            context=context,
            participant_prompt=participant_prompt,
        ),
        max_tokens=256,
    )
    answer_completed_at = _timestamp()
    answer_payload = _parse_answer(answer_completion.content)
    deterministic_scores = _deterministic_scores(
        case=case,
        payload=answer_payload,
        evidence_ids=evidence_ids,
    )
    judge_started_at = _timestamp()
    judge_completion = client.complete(
        _judge_messages(
            case=case,
            context=context,
            candidate_answer=answer_completion.content,
        ),
        max_tokens=192,
    )
    judge_completed_at = _timestamp()
    judge = _parse_judge(judge_completion.content)
    criteria = dict(deterministic_scores)
    for name, weight in JUDGE_WEIGHTS.items():
        criteria[name] = round(float(getattr(judge, name)) * weight, 2)

    return {
        "partition": case.partition,
        "case_id": case.case_id,
        "domain": case.domain,
        "difficulty": case.difficulty,
        "input": {"question": case.question, "context": context},
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
        "timing": {
            "answer_started_at": answer_started_at,
            "answer_completed_at": answer_completed_at,
            "judge_started_at": judge_started_at,
            "judge_completed_at": judge_completed_at,
        },
    }


def _load_context(
    *, public_directory: Path, context_files: tuple[str, str]
) -> tuple[str, frozenset[str]]:
    public_root = public_directory.resolve()
    parts: list[str] = []
    for relative_path in context_files:
        path = (public_root / relative_path).resolve()
        if not path.is_relative_to(public_root):
            raise ValueError("Evaluation context path escapes the public dataset.")
        try:
            content = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError as exc:
            raise ValueError(f"Evaluation context not found: {relative_path}") from exc
        if not content:
            raise ValueError(f"Evaluation context is empty: {relative_path}")
        parts.append(f"# Source file: {relative_path}\n\n{content}")
    context = "\n\n---\n\n".join(parts)
    evidence_ids = frozenset(EVIDENCE_ID_PATTERN.findall(context))
    if not evidence_ids:
        raise ValueError("Evaluation context contains no evidence IDs.")
    return context, evidence_ids


def _answer_messages(
    *, question: str, context: str, participant_prompt: str
) -> tuple[Message, ...]:
    return (
        {"role": "system", "content": FIXED_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"""<context>
{context}
</context>

<question>
{question}
</question>

<participant_prompt>
{participant_prompt}
</participant_prompt>""",
        },
    )


def _judge_messages(
    *, case: EvaluationCase, context: str, candidate_answer: str
) -> tuple[Message, ...]:
    payload = {
        "question": case.question,
        "context": context,
        "candidate_answer": candidate_answer,
        "reference": {
            "answer": case.reference.answer,
            "citations": case.reference.citations,
            "escalate": case.reference.escalate,
            "key_points": case.reference.key_points,
        },
        "rubric": {
            "required_points": case.rubric.required_points,
            "prohibited_claims": case.rubric.prohibited_claims,
            "non_authoritative_evidence": case.rubric.non_authoritative_evidence,
        },
    }
    return (
        {
            "role": "system",
            "content": (
                "Score the candidate support answer against the supplied reference and "
                "evidence. Return one JSON object with integer scores from 0 to 100 for "
                "answer_relevance, instruction_following, and faithfulness, plus a "
                "reasons object containing one short reason for each score."
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    )


def _parse_answer(response: str) -> dict[str, object] | None:
    try:
        payload = cast(object, json.loads(response))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return cast(dict[str, object], payload)


def _deterministic_scores(
    *,
    case: EvaluationCase,
    payload: dict[str, object] | None,
    evidence_ids: frozenset[str],
) -> dict[str, float]:
    scores = {name: 0.0 for name in DETERMINISTIC_CRITERIA}
    if payload is None:
        return scores

    answer = payload.get("answer")
    citations_value = payload.get("citations")
    escalate = payload.get("escalate")
    schema_valid = (
        set(payload) == {"answer", "citations", "escalate"}
        and isinstance(answer, str)
        and bool(answer.strip())
        and len(answer.split()) <= 100
        and isinstance(citations_value, list)
        and isinstance(escalate, bool)
    )
    if schema_valid:
        scores["json_schema"] = 10.0

    citations: list[str] = []
    if isinstance(citations_value, list):
        raw_citations = cast(list[object], citations_value)
        if raw_citations and all(
            isinstance(value, str) and bool(value) for value in raw_citations
        ):
            citations = cast(list[str], raw_citations)
            if len(citations) == len(set(citations)) and set(citations).issubset(
                evidence_ids
            ):
                scores["citation_validity"] = 10.0

    groups = case.rubric.required_citation_groups
    if groups:
        covered = sum(bool(set(group).intersection(citations)) for group in groups)
        scores["evidence_coverage"] = round(10.0 * covered / len(groups), 2)
    else:
        scores["evidence_coverage"] = 10.0

    if isinstance(escalate, bool) and escalate is case.reference.escalate:
        scores["escalation"] = 10.0
    return scores


def _parse_judge(response: str) -> _JudgePayload:
    try:
        payload = cast(object, json.loads(response))
        return _JudgePayload.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError("Judge response did not match the scoring contract.") from exc


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    names = (*DETERMINISTIC_CRITERIA, *JUDGE_WEIGHTS)
    if not results:
        return {
            "case_count": 0,
            "criteria": {name: 0.0 for name in names},
            "score": 0.0,
        }
    criteria = {
        name: round(
            sum(float(result["criteria"][name]) for result in results) / len(results),
            2,
        )
        for name in names
    }
    return {
        "case_count": len(results),
        "criteria": criteria,
        "score": round(sum(criteria.values()), 2),
    }


def _timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
