from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

from hkpug_challenge.context_routing import route_context
from hkpug_challenge.difficulty_experiment import (
    PRODUCTION_PROFILE_ORDER,
    contract_gated_score,
    production_adversarial_case,
    production_prompt,
)
from hkpug_challenge.evaluation_bank import ARCHETYPES, load_evaluation_bank
from hkpug_challenge.fireworks import FIREWORKS_MODEL, JUDGE_MODEL, FireworksClient
from hkpug_challenge.scoring import (
    DISCOVERY_WEIGHT,
    HOLDOUT_WEIGHT,
    MAX_RUN_TOKENS,
    score_case,
)


TOURNAMENT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PUBLIC_DIRECTORY = REPOSITORY_ROOT / "public"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation-bank", required=True, type=Path)
    parser.add_argument("--profile", required=True, choices=PRODUCTION_PROFILE_ORDER)
    parser.add_argument("--output-path", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = os.environ.get("FIREWORKS_API_KEY", "")
    if not api_key:
        raise SystemExit("FIREWORKS_API_KEY is required.")

    bank = load_evaluation_bank(
        args.evaluation_bank,
        public_directory=PUBLIC_DIRECTORY,
    )
    participant_prompt = production_prompt(args.profile)
    retrieval_usage = _empty_usage()
    scoring_usage = _empty_scoring_usage()
    records: list[dict[str, Any]] = []
    route_records: list[dict[str, object]] = []
    for index, original_case in enumerate(bank.cases, start=1):
        case = production_adversarial_case(original_case)
        print(
            f"[production-readiness {args.profile} "
            f"{index:02d}/{len(bank.cases):02d}] {case.case_id}",
            file=sys.stderr,
            flush=True,
        )
        route = route_context(
            public_directory=PUBLIC_DIRECTORY,
            question=case.question,
            participant_prompt=participant_prompt,
            client=_candidate_client(api_key),
        )
        _record_usage(
            retrieval_usage,
            prompt_tokens=route.prompt_tokens,
            completion_tokens=route.completion_tokens,
        )
        expected = set(case.context_files)
        selected = set(route.context_files)
        route_records.append(
            {
                "partition": case.partition,
                "exact_match": selected == expected,
                "domain_context_found": bool(
                    selected.intersection(expected - {"contexts/company_handbook.md"})
                ),
            }
        )
        result = score_case(
            case=case,
            participant_prompt=participant_prompt,
            public_directory=PUBLIC_DIRECTORY,
            candidate_client=_candidate_client(api_key),
            judge_client=_judge_client(api_key),
            candidate_model=FIREWORKS_MODEL,
            token_usage=scoring_usage,
            max_run_tokens=MAX_RUN_TOKENS,
            candidate_context_files=route.context_files,
        )
        combined_total = (
            retrieval_usage["total_tokens"] + scoring_usage["total"]["total_tokens"]
        )
        if combined_total > MAX_RUN_TOKENS:
            raise ValueError(
                f"Production-readiness run exceeded the {MAX_RUN_TOKENS} token limit."
            )
        gated = contract_gated_score(result)
        records.append(
            {
                "partition": case.partition,
                "archetype": case.archetype,
                "raw_score": result["score"],
                "gated_score": gated.score,
                "gates": gated.caps,
                "criteria": result["criteria"],
                "judge_attempts": result["usage"]["judge_attempts"],
            }
        )

    partitions = {
        partition: _aggregate(
            [record for record in records if record["partition"] == partition]
        )
        for partition in ("discovery", "holdout")
    }
    overall = {
        name: round(
            float(partitions["discovery"][name]) * DISCOVERY_WEIGHT
            + float(partitions["holdout"][name]) * HOLDOUT_WEIGHT,
            2,
        )
        for name in ("raw_score", "gated_score")
    }
    output = {
        "schema_version": 1,
        "seed": 0,
        "profile": args.profile,
        "prompt_sha256": sha256(participant_prompt.encode("utf-8")).hexdigest(),
        "candidate_model": FIREWORKS_MODEL,
        "judge_model": JUDGE_MODEL,
        "case_count": len(records),
        "call_count": len(records) * 2
        + sum(int(record["judge_attempts"]) for record in records),
        "overall": overall,
        "partitions": partitions,
        "archetypes": {
            archetype: _aggregate(
                [record for record in records if record["archetype"] == archetype]
            )
            for archetype in ARCHETYPES
        },
        "routing": _routing_summary(route_records),
        "token_usage": _combined_usage(
            retrieval=retrieval_usage,
            scoring=scoring_usage,
        ),
    }
    output_path = (
        args.output_path
        or TOURNAMENT_ROOT
        / f".local/playground/production-readiness-{args.profile}.json"
    ).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        output_path.chmod(0o600)
    print(
        json.dumps(
            {
                "profile": args.profile,
                "overall": overall,
                "routing": output["routing"],
                "token_usage": output["token_usage"],
            },
            sort_keys=True,
        )
    )
    return 0


def _candidate_client(api_key: str) -> FireworksClient:
    return FireworksClient(
        api_key,
        model=FIREWORKS_MODEL,
        empty_on_missing_content=True,
    )


def _judge_client(api_key: str) -> FireworksClient:
    return FireworksClient(api_key, model=JUDGE_MODEL)


def _aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        raise ValueError("Production-readiness aggregate cannot be empty.")
    count = len(records)
    criteria_names = tuple(records[0]["criteria"])
    return {
        "case_count": count,
        "raw_score": round(
            sum(float(record["raw_score"]) for record in records) / count,
            2,
        ),
        "gated_score": round(
            sum(float(record["gated_score"]) for record in records) / count,
            2,
        ),
        "criteria": {
            name: round(
                sum(float(record["criteria"][name]) for record in records) / count,
                2,
            )
            for name in criteria_names
        },
        "gate_counts": dict(
            sorted(
                Counter(gate for record in records for gate in record["gates"]).items()
            )
        ),
    }


def _routing_summary(records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "exact_matches": sum(record["exact_match"] is True for record in records),
        "domain_context_hits": sum(
            record["domain_context_found"] is True for record in records
        ),
        "case_count": len(records),
        "discovery_exact_matches": sum(
            record["exact_match"] is True and record["partition"] == "discovery"
            for record in records
        ),
        "holdout_exact_matches": sum(
            record["exact_match"] is True and record["partition"] == "holdout"
            for record in records
        ),
    }


def _empty_usage() -> dict[str, int]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def _empty_scoring_usage() -> dict[str, dict[str, int]]:
    return {bucket: _empty_usage() for bucket in ("candidate", "judge", "total")}


def _record_usage(
    usage: dict[str, int], *, prompt_tokens: int, completion_tokens: int
) -> None:
    usage["prompt_tokens"] += prompt_tokens
    usage["completion_tokens"] += completion_tokens
    usage["total_tokens"] += prompt_tokens + completion_tokens


def _combined_usage(
    *, retrieval: dict[str, int], scoring: dict[str, dict[str, int]]
) -> dict[str, object]:
    total = {
        name: retrieval[name] + scoring["total"][name]
        for name in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    return {
        "retrieval": retrieval,
        "candidate": scoring["candidate"],
        "judge": scoring["judge"],
        "total": total,
        "hard_limit_enforced": True,
        "hard_limit_tokens": MAX_RUN_TOKENS,
    }


if __name__ == "__main__":
    raise SystemExit(main())
