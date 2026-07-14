from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from hkpug_challenge.context_routing import route_context
from hkpug_challenge.evaluation_bank import load_evaluation_bank
from hkpug_challenge.fireworks import FIREWORKS_MODEL, JUDGE_MODEL, FireworksClient
from hkpug_challenge.scoring import _aggregate, _score_case
from hkpug_challenge.submission import load_prompt_text


TOURNAMENT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PUBLIC_DIRECTORY = REPOSITORY_ROOT / "public"
DEFAULT_PROMPT_PATH = REPOSITORY_ROOT / "starter" / "prompt.example.txt"
DEFAULT_OUTPUT_PATH = (
    TOURNAMENT_ROOT / ".local" / "playground" / "context-selection-bank.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation-bank", required=True, type=Path)
    parser.add_argument("--prompt-path", type=Path, default=DEFAULT_PROMPT_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = os.environ.get("FIREWORKS_API_KEY", "")
    if not api_key:
        raise SystemExit("FIREWORKS_API_KEY is required.")

    participant_prompt = load_prompt_text(args.prompt_path)
    bank = load_evaluation_bank(
        args.evaluation_bank,
        public_directory=PUBLIC_DIRECTORY,
    )
    scoring_usage = _empty_scoring_usage()
    retrieval_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    results: list[dict[str, Any]] = []
    route_records: list[dict[str, object]] = []
    for index, case in enumerate(bank.cases, start=1):
        print(
            f"[context-selection {index:02d}/{len(bank.cases):02d}] {case.case_id}",
            file=sys.stderr,
            flush=True,
        )
        route = route_context(
            public_directory=PUBLIC_DIRECTORY,
            question=case.question,
            participant_prompt=participant_prompt,
            client=_candidate_client(api_key),
        )
        _record_retrieval_usage(
            retrieval_usage,
            prompt_tokens=route.prompt_tokens,
            completion_tokens=route.completion_tokens,
        )
        expected = set(case.context_files)
        selected = set(route.context_files)
        route_records.append(
            {
                "case_id": case.case_id,
                "partition": case.partition,
                "exact_match": selected == expected,
                "domain_context_found": bool(
                    selected.intersection(expected - {"contexts/company_handbook.md"})
                ),
            }
        )
        results.append(
            _score_case(
                case=case,
                participant_prompt=participant_prompt,
                public_directory=PUBLIC_DIRECTORY,
                candidate_client=_candidate_client(api_key),
                judge_client=_judge_client(api_key),
                candidate_model=FIREWORKS_MODEL,
                token_usage=scoring_usage,
                max_run_tokens=2**63 - 1,
                candidate_context_files=route.context_files,
            )
        )

    discovery_results = [
        result for result in results if result["partition"] == "discovery"
    ]
    holdout_results = [result for result in results if result["partition"] == "holdout"]
    discovery = _aggregate(discovery_results)
    holdout = _aggregate(holdout_results)
    overall_score = round(
        float(discovery["score"]) * 0.75 + float(holdout["score"]) * 0.25,
        2,
    )
    output = {
        "schema_version": 1,
        "seed": 0,
        "candidate_model": FIREWORKS_MODEL,
        "judge_model": JUDGE_MODEL,
        "case_count": len(results),
        "call_count": len(results) * 3,
        "overall_score": overall_score,
        "discovery": discovery,
        "holdout": holdout,
        "routing": _routing_summary(route_records),
        "token_usage": _combined_usage(
            retrieval=retrieval_usage,
            scoring=scoring_usage,
        ),
    }
    output_path = args.output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        output_path.chmod(0o600)
    print(json.dumps(output, sort_keys=True))
    return 0


def _candidate_client(api_key: str) -> FireworksClient:
    return FireworksClient(
        api_key,
        model=FIREWORKS_MODEL,
        empty_on_missing_content=True,
    )


def _judge_client(api_key: str) -> FireworksClient:
    return FireworksClient(api_key, model=JUDGE_MODEL)


def _empty_scoring_usage() -> dict[str, dict[str, int]]:
    return {
        bucket: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        for bucket in ("candidate", "judge", "total")
    }


def _record_retrieval_usage(
    usage: dict[str, int], *, prompt_tokens: int, completion_tokens: int
) -> None:
    usage["prompt_tokens"] += prompt_tokens
    usage["completion_tokens"] += completion_tokens
    usage["total_tokens"] += prompt_tokens + completion_tokens


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
        "hard_limit_enforced": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
