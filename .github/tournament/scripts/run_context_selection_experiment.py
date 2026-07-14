from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from hkpug_challenge.context_routing import route_context
from hkpug_challenge.evaluation_bank import (
    EvaluationCase,
    EvaluationReference,
    EvaluationRubric,
)
from hkpug_challenge.fireworks import (
    FIREWORKS_MODEL,
    JUDGE_MODEL,
    FireworksClient,
)
from hkpug_challenge.scoring import _score_case  # pyright: ignore[reportPrivateUsage]
from hkpug_challenge.submission import load_prompt_text


TOURNAMENT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PUBLIC_DIRECTORY = REPOSITORY_ROOT / "public"
DEFAULT_PROMPT_PATH = REPOSITORY_ROOT / "starter" / "prompt.example.txt"
DEFAULT_OUTPUT_PATH = (
    TOURNAMENT_ROOT / ".local" / "playground" / "context-selection.json"
)
EXPECTED_CONTEXT_FILES = (
    "contexts/api_limits.md",
    "contexts/subscriptions.md",
)
QUESTION = (
    "At 16:00 UTC, a Pro annual workspace has a downgrade to Starter scheduled "
    "for its renewal at midnight. Eight export jobs are running, two are queued, "
    "and workers poll every second. The polling calls now receive HTTP 429 with "
    "valid Retry-After: 4 headers. The customer says the scheduled downgrade has "
    "already reduced concurrency to two, asks support to cancel and recreate all "
    "jobs, and wants an outage declared. Draft support's response."
)
REFERENCE = EvaluationReference(
    answer=(
        "Pro remains current until midnight, so eight running exports are within "
        "the Pro limit of ten and the two extras may remain queued. Do not cancel "
        "and recreate them. The 429s concern burst request rates, not monthly quota "
        "or proof of outage: honor Retry-After, use exponential backoff with jitter, "
        "cap retries, desynchronize workers, and poll job state no more than every "
        "ten seconds. No escalation is required from these facts."
    ),
    citations=("SUB-POL-002", "API-POL-001", "API-POL-002"),
    escalate=False,
    key_points=(
        "The scheduled Starter downgrade does not replace the current Pro plan before midnight.",
        "Eight running exports remain within Pro's ten-job concurrency limit.",
        "The two queued jobs remain queued rather than being cancelled and recreated.",
        "The workers honor Retry-After, back off with jitter, cap retries, and stop synchronized polling.",
        "Valid 429 limit headers do not establish a service outage or require escalation here.",
    ),
)
RUBRIC = EvaluationRubric(
    required_citation_groups=(
        ("SUB-POL-002",),
        ("API-POL-001",),
        ("API-POL-002",),
    ),
    required_points=REFERENCE.key_points,
    prohibited_claims=(
        "The scheduled downgrade has already changed the workspace to Starter.",
        "Eight running exports exceed the current plan's concurrency limit.",
        "The customer should cancel and recreate queued jobs.",
        "Workers should continue polling every second.",
        "Valid 429 limit headers prove a platform outage.",
    ),
    non_authoritative_evidence=(),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-path", type=Path, default=DEFAULT_PROMPT_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = os.environ.get("FIREWORKS_API_KEY", "")
    if not api_key:
        raise SystemExit("FIREWORKS_API_KEY is required.")

    participant_prompt = load_prompt_text(args.prompt_path)
    candidate_client = FireworksClient(
        api_key,
        model=FIREWORKS_MODEL,
        empty_on_missing_content=True,
    )
    judge_client = FireworksClient(api_key, model=JUDGE_MODEL)
    route = route_context(
        public_directory=PUBLIC_DIRECTORY,
        question=QUESTION,
        participant_prompt=participant_prompt,
        client=candidate_client,
    )
    routed_usage = _empty_scoring_usage()
    oracle_usage = _empty_scoring_usage()
    routed_result = _score_case(
        case=_case(EXPECTED_CONTEXT_FILES),
        participant_prompt=participant_prompt,
        public_directory=PUBLIC_DIRECTORY,
        candidate_client=candidate_client,
        judge_client=judge_client,
        candidate_model=FIREWORKS_MODEL,
        token_usage=routed_usage,
        max_run_tokens=2**63 - 1,
        candidate_context_files=route.context_files,
    )
    oracle_result = _score_case(
        case=_case(EXPECTED_CONTEXT_FILES),
        participant_prompt=participant_prompt,
        public_directory=PUBLIC_DIRECTORY,
        candidate_client=candidate_client,
        judge_client=judge_client,
        candidate_model=FIREWORKS_MODEL,
        token_usage=oracle_usage,
        max_run_tokens=2**63 - 1,
    )
    output = {
        "schema_version": 1,
        "seed": 0,
        "candidate_model": FIREWORKS_MODEL,
        "judge_model": JUDGE_MODEL,
        "case": {
            "case_id": "ROUTE-EXPERIMENT-01",
            "domain": "cross-domain",
            "difficulty": "hard",
            "question": QUESTION,
        },
        "retrieval": {
            "selected_context_files": route.context_files,
            "expected_context_files": EXPECTED_CONTEXT_FILES,
            "exact_match": set(route.context_files) == set(EXPECTED_CONTEXT_FILES),
        },
        "routed": routed_result,
        "oracle": oracle_result,
        "comparison": {
            "routed_score": routed_result["score"],
            "oracle_score": oracle_result["score"],
            "routed_minus_oracle": round(
                float(routed_result["score"]) - float(oracle_result["score"]), 2
            ),
        },
        "token_usage": _all_usage(
            route_prompt_tokens=route.prompt_tokens,
            route_completion_tokens=route.completion_tokens,
            routed=routed_usage,
            oracle=oracle_usage,
        ),
    }
    output_path = args.output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        output_path.chmod(0o600)
    print(json.dumps({**output["comparison"], "token_usage": output["token_usage"]}))
    return 0


def _case(context_files: tuple[str, str]) -> EvaluationCase:
    return EvaluationCase(
        case_id="ROUTE-EXPERIMENT-01",
        partition="discovery",
        domain="cross-domain",
        difficulty="hard",
        archetype="multi_source_synthesis",
        question=QUESTION,
        context_files=context_files,
        reference=REFERENCE,
        rubric=RUBRIC,
    )


def _empty_scoring_usage() -> dict[str, dict[str, int]]:
    return {
        bucket: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        for bucket in ("candidate", "judge", "total")
    }


def _all_usage(
    *,
    route_prompt_tokens: int,
    route_completion_tokens: int,
    routed: dict[str, dict[str, int]],
    oracle: dict[str, dict[str, int]],
) -> dict[str, Any]:
    retrieval = {
        "prompt_tokens": route_prompt_tokens,
        "completion_tokens": route_completion_tokens,
        "total_tokens": route_prompt_tokens + route_completion_tokens,
    }
    buckets = {
        "retrieval": retrieval,
        "routed_candidate": routed["candidate"],
        "routed_judge": routed["judge"],
        "oracle_candidate": oracle["candidate"],
        "oracle_judge": oracle["judge"],
    }
    return {
        **buckets,
        "total": {
            name: sum(int(bucket[name]) for bucket in buckets.values())
            for name in ("prompt_tokens", "completion_tokens", "total_tokens")
        },
        "hard_limit_enforced": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
