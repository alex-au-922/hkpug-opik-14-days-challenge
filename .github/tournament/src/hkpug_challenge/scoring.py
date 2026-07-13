from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
)

from .dataset import EVIDENCE_ID_PATTERN
from .evaluation_bank import PARTITION_COUNTS, EvaluationCase
from .fireworks import (
    Completion,
    EXPERIMENTAL_CANDIDATE_MAX_TOKENS,
    EXPERIMENTAL_CANDIDATE_MODELS,
    FIREWORKS_MODEL,
    JUDGE_TIERS,
    JUDGE_MODEL,
    CompletionClient,
    scoring_judge_response_format,
    validate_scoring_models,
)
from .models import Message
from .playground import FIXED_SYSTEM_PROMPT


DISCOVERY_WEIGHT = 0.75
HOLDOUT_WEIGHT = 0.25
MAX_RUN_TOKENS = 500_000
JUDGE_MAX_TOKENS = 1_536
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
SHARED_CONTEXT_PATH = "contexts/company_handbook.md"


class _JudgeReasons(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    answer_relevance: str
    instruction_following: str
    faithfulness: str


class _JudgePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    answer_relevance: StrictInt
    instruction_following: StrictInt
    faithfulness: StrictInt
    required_points_met: tuple[StrictInt, ...] = ()
    prohibited_claims_present: tuple[StrictInt, ...] = ()
    non_authoritative_evidence_used: tuple[StrictStr, ...] = ()
    reasons: _JudgeReasons

    @field_validator(
        "answer_relevance", "instruction_following", "faithfulness", mode="after"
    )
    @classmethod
    def validate_tier(cls, value: int) -> int:
        if value not in JUDGE_TIERS:
            raise ValueError(f"Judge scores must be one of {JUDGE_TIERS}.")
        return value

    @field_validator("required_points_met", "prohibited_claims_present", mode="after")
    @classmethod
    def validate_audit_indexes(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if any(value < 0 for value in values):
            raise ValueError("Judge audit indexes must be zero-based.")
        if len(set(values)) != len(values):
            raise ValueError("Judge audit indexes must not contain duplicates.")
        return values

    @field_validator("non_authoritative_evidence_used", mode="after")
    @classmethod
    def validate_audit_evidence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value for value in values):
            raise ValueError("Judge audit evidence IDs must not be empty.")
        if len(set(values)) != len(values):
            raise ValueError("Judge audit evidence IDs must not contain duplicates.")
        return values


def score_prompt(
    *,
    team_id: str,
    attempt: int,
    run_id: str,
    participant_prompt: str,
    cases: tuple[EvaluationCase, ...],
    public_directory: Path,
    candidate_client: CompletionClient,
    judge_client: CompletionClient,
    candidate_model: str = FIREWORKS_MODEL,
    judge_model: str = JUDGE_MODEL,
    max_calls: int = 100,
    max_run_tokens: int = MAX_RUN_TOKENS,
    include_holdout_details: bool = False,
    on_case_start: Callable[[int, int], None] | None = None,
    allow_experimental_candidate: bool = False,
) -> dict[str, Any]:
    prompt = participant_prompt.strip()
    if not prompt:
        raise ValueError("Participant prompt must not be empty.")
    if attempt < 1:
        raise ValueError("Attempt must be positive.")
    if max_run_tokens < 1:
        raise ValueError("Run token limit must be positive.")
    candidate_model, judge_model = validate_scoring_models(
        candidate_model,
        judge_model,
        allow_experimental_candidate=allow_experimental_candidate,
    )
    if dict(Counter(case.partition for case in cases)) != PARTITION_COUNTS:
        raise ValueError("Scoring requires exactly 40 discovery and 10 holdout cases.")
    required_calls = len(cases) * 2
    if required_calls > max_calls:
        raise ValueError(
            f"Scoring requires {required_calls} calls, above the {max_calls} call limit."
        )

    started_at = _timestamp()
    results: list[dict[str, Any]] = []
    token_usage = _empty_token_usage()
    for current, case in enumerate(cases, start=1):
        if on_case_start is not None:
            on_case_start(current, len(cases))
        results.append(
            _score_case(
                case=case,
                participant_prompt=prompt,
                public_directory=public_directory,
                candidate_client=candidate_client,
                judge_client=judge_client,
                candidate_model=candidate_model,
                token_usage=token_usage,
                max_run_tokens=max_run_tokens,
            )
        )
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
    if include_holdout_details:
        holdout["cases"] = [
            {key: value for key, value in result.items() if key != "partition"}
            for result in holdout_results
        ]

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
        "model": candidate_model,
        "judge_model": judge_model,
        "prompt_sha256": sha256(prompt.encode("utf-8")).hexdigest(),
        "weights": {
            "discovery": DISCOVERY_WEIGHT,
            "holdout": HOLDOUT_WEIGHT,
        },
        "discovery": discovery,
        "holdout": holdout,
        "overall_score": overall_score,
        "token_usage": token_usage,
        "call_count": required_calls,
        "started_at": started_at,
        "completed_at": _timestamp(),
    }


def _score_case(
    *,
    case: EvaluationCase,
    participant_prompt: str,
    public_directory: Path,
    candidate_client: CompletionClient,
    judge_client: CompletionClient,
    candidate_model: str,
    token_usage: dict[str, dict[str, int]],
    max_run_tokens: int,
) -> dict[str, Any]:
    context, evidence_ids, judge_context = _load_context(
        public_directory=public_directory,
        context_files=case.context_files,
    )
    answer_started_at = _timestamp()
    answer_completion = candidate_client.complete(
        _answer_messages(
            question=case.question,
            context=context,
            participant_prompt=participant_prompt,
        ),
        max_tokens=(
            EXPERIMENTAL_CANDIDATE_MAX_TOKENS
            if candidate_model in EXPERIMENTAL_CANDIDATE_MODELS
            else 256
        ),
    )
    _record_token_usage(
        token_usage=token_usage,
        bucket="candidate",
        completion=answer_completion,
        max_run_tokens=max_run_tokens,
    )
    answer_completed_at = _timestamp()
    answer_payload = _parse_answer(answer_completion.content)
    deterministic_scores = _deterministic_scores(
        case=case,
        payload=answer_payload,
        evidence_ids=evidence_ids,
    )
    judge_started_at = _timestamp()
    judge_completion = judge_client.complete(
        _judge_messages(
            case=case,
            context=judge_context,
            candidate_answer=answer_completion.content,
        ),
        max_tokens=JUDGE_MAX_TOKENS,
        response_format=scoring_judge_response_format(
            required_point_count=len(case.rubric.required_points),
            prohibited_claim_count=len(case.rubric.prohibited_claims),
            non_authoritative_evidence=case.rubric.non_authoritative_evidence,
        ),
    )
    _record_token_usage(
        token_usage=token_usage,
        bucket="judge",
        completion=judge_completion,
        max_run_tokens=max_run_tokens,
    )
    judge_completed_at = _timestamp()
    judge = _parse_judge(judge_completion.content, case=case)
    raw_judge_scores = _raw_judge_scores(judge)
    judge_scores = _capped_judge_scores(case=case, judge=judge)
    cap_explanations = _cap_explanations(
        case=case,
        judge=judge,
        raw_scores=raw_judge_scores,
        effective_scores=judge_scores,
    )
    criteria = dict(deterministic_scores)
    for name, weight in JUDGE_WEIGHTS.items():
        criteria[name] = round(float(judge_scores[name]) * weight, 2)
    reasons = {
        "answer_relevance": judge.reasons.answer_relevance,
        "instruction_following": judge.reasons.instruction_following,
        "faithfulness": judge.reasons.faithfulness,
    }
    reasons.update(cap_explanations)

    return {
        "partition": case.partition,
        "case_id": case.case_id,
        "domain": case.domain,
        "difficulty": case.difficulty,
        "input": {"question": case.question, "context": context},
        "output": answer_completion.content,
        "criteria": criteria,
        "score": round(sum(criteria.values()), 2),
        "reasons": reasons,
        "judge": {
            "raw_tiers": raw_judge_scores,
            "effective_tiers": judge_scores,
            "audit": {
                "required_points_met": list(judge.required_points_met),
                "prohibited_claims_present": list(judge.prohibited_claims_present),
                "non_authoritative_evidence_used": list(
                    judge.non_authoritative_evidence_used
                ),
            },
            "cap_explanations": cap_explanations,
        },
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
) -> tuple[str, frozenset[str], str]:
    public_root = public_directory.resolve()
    parts: list[str] = []
    judge_parts: list[str] = []
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
        part = f"# Source file: {relative_path}\n\n{content}"
        parts.append(part)
        if relative_path != SHARED_CONTEXT_PATH:
            judge_parts.append(part)
    context = "\n\n---\n\n".join(parts)
    evidence_ids = frozenset(EVIDENCE_ID_PATTERN.findall(context))
    if not evidence_ids:
        raise ValueError("Evaluation context contains no evidence IDs.")
    if not judge_parts:
        raise ValueError("Evaluation context contains no domain evidence.")
    return context, evidence_ids, "\n\n---\n\n".join(judge_parts)


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
                "Score the candidate support answer against the supplied context, "
                "reference, and rubric. Use the context to verify factual claims; do "
                "not penalize a supported detail merely because the reference omits "
                "it. Assign exactly one tier (0, 25, 50, 75, or 100) to each of "
                "answer_relevance, instruction_following, and faithfulness. Use 0 when "
                "the criterion is unmet, 25 for major failures, 50 for material errors "
                "or omissions, 75 for minor errors or omissions, and 100 when fully "
                "met. Judge only substantive answer quality here. JSON shape, citation "
                "validity, evidence coverage, and escalation matching are scored "
                "separately and must not lower these tiers. "
                "Audit required_points_met as zero-based indexes of every required "
                "point materially satisfied by the candidate. Audit "
                "prohibited_claims_present as zero-based indexes of every prohibited "
                "claim present. Audit non_authoritative_evidence_used as IDs from the "
                "rubric list that the candidate treats as authority, not sources it "
                "merely identifies as non-authoritative. Use empty arrays when none "
                "apply. Every audit array must contain unique, zero-based indexes or "
                "IDs only; never repeat an item and never invent one outside the "
                "supplied rubric. Return one JSON object with the three tier scores, every audit "
                "field present in the response schema, and a reasons object containing "
                "one short reason for each score."
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


def _parse_judge(response: str, *, case: EvaluationCase) -> _JudgePayload:
    try:
        payload = cast(object, json.loads(response))
        judge = _JudgePayload.model_validate(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Judge response did not match the scoring contract "
            f"(json_error={exc.msg}; line={exc.lineno}; column={exc.colno}; "
            f"{_judge_response_diagnostic(response)})."
        ) from exc
    except ValidationError as exc:
        locations = ",".join(
            _validation_location(error.get("loc", ()))
            for error in exc.errors()
        )
        error_types = ",".join(
            str(error.get("type", "unknown")) for error in exc.errors()
        )
        raise ValueError(
            "Judge response did not match the scoring contract "
            f"(validation_locations={locations}; validation_types={error_types}; "
            f"{_judge_response_diagnostic(response)})."
        ) from exc

    required_point_count = len(case.rubric.required_points)
    prohibited_claim_count = len(case.rubric.prohibited_claims)
    audit_outside_rubric = (
        any(index >= required_point_count for index in judge.required_points_met)
        or any(
            index >= prohibited_claim_count for index in judge.prohibited_claims_present
        )
        or not set(judge.non_authoritative_evidence_used).issubset(
            case.rubric.non_authoritative_evidence
        )
    )
    if audit_outside_rubric:
        raise ValueError(
            "Judge response did not match the scoring contract "
            f"(audit=out-of-rubric; {_judge_response_diagnostic(response)})."
        )
    return judge


def _validation_location(value: object) -> str:
    if isinstance(value, tuple):
        parts = value
    elif isinstance(value, list):
        parts = tuple(value)
    else:
        parts = (value,)
    return ".".join(str(part) for part in parts) or "<root>"


def _judge_response_diagnostic(response: str) -> str:
    return (
        f"response_chars={len(response)}; "
        f"response_sha256={sha256(response.encode('utf-8')).hexdigest()}"
    )


def _capped_judge_scores(
    *, case: EvaluationCase, judge: _JudgePayload
) -> dict[str, int]:
    required_point_count = len(case.rubric.required_points)
    relevance_cap = JUDGE_TIERS[-1]
    if required_point_count:
        coverage_tier = (
            len(judge.required_points_met)
            * (len(JUDGE_TIERS) - 1)
            // required_point_count
        )
        relevance_cap = JUDGE_TIERS[coverage_tier]

    faithfulness_cap = (
        50
        if judge.prohibited_claims_present or judge.non_authoritative_evidence_used
        else JUDGE_TIERS[-1]
    )
    return {
        "answer_relevance": min(judge.answer_relevance, relevance_cap),
        "instruction_following": judge.instruction_following,
        "faithfulness": min(judge.faithfulness, faithfulness_cap),
    }


def _raw_judge_scores(judge: _JudgePayload) -> dict[str, int]:
    return {
        "answer_relevance": judge.answer_relevance,
        "instruction_following": judge.instruction_following,
        "faithfulness": judge.faithfulness,
    }


def _cap_explanations(
    *,
    case: EvaluationCase,
    judge: _JudgePayload,
    raw_scores: dict[str, int],
    effective_scores: dict[str, int],
) -> dict[str, str]:
    explanations: dict[str, str] = {}
    raw_relevance = raw_scores["answer_relevance"]
    effective_relevance = effective_scores["answer_relevance"]
    if effective_relevance < raw_relevance:
        explanations["answer_relevance"] = (
            f"Answer relevance tier capped from {raw_relevance} to "
            f"{effective_relevance}: {len(judge.required_points_met)} of "
            f"{len(case.rubric.required_points)} required points were materially "
            "satisfied."
        )

    raw_faithfulness = raw_scores["faithfulness"]
    effective_faithfulness = effective_scores["faithfulness"]
    if effective_faithfulness < raw_faithfulness:
        hazards: list[str] = []
        if judge.prohibited_claims_present:
            indexes = ", ".join(str(index) for index in judge.prohibited_claims_present)
            hazards.append(f"prohibited claim indexes: {indexes}")
        if judge.non_authoritative_evidence_used:
            evidence_ids = ", ".join(judge.non_authoritative_evidence_used)
            hazards.append(f"non-authoritative evidence IDs: {evidence_ids}")
        explanations["faithfulness"] = (
            f"Faithfulness tier capped from {raw_faithfulness} to "
            f"{effective_faithfulness}: {'; '.join(hazards)}."
        )
    return explanations


def _empty_token_usage() -> dict[str, dict[str, int]]:
    return {
        bucket: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        for bucket in ("candidate", "judge", "total")
    }


def _record_token_usage(
    *,
    token_usage: dict[str, dict[str, int]],
    bucket: str,
    completion: Completion,
    max_run_tokens: int,
) -> None:
    bucket_usage = token_usage[bucket]
    total_usage = token_usage["total"]
    bucket_usage["prompt_tokens"] += completion.prompt_tokens
    bucket_usage["completion_tokens"] += completion.completion_tokens
    bucket_usage["total_tokens"] += (
        completion.prompt_tokens + completion.completion_tokens
    )
    total_usage["prompt_tokens"] += completion.prompt_tokens
    total_usage["completion_tokens"] += completion.completion_tokens
    total_usage["total_tokens"] += (
        completion.prompt_tokens + completion.completion_tokens
    )
    if total_usage["total_tokens"] > max_run_tokens:
        raise ValueError(f"Scoring exceeded the {max_run_tokens} token limit.")


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
