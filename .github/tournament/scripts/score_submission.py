from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, cast

from hkpug_challenge.evaluation_bank import load_evaluation_bank
from hkpug_challenge.fireworks import (
    FireworksClient,
    validate_scoring_models,
)
from hkpug_challenge.scoring import score_prompt
from hkpug_challenge.submission import verify_submission
from hkpug_challenge.traces import write_trace_bundle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission-dir", required=True, type=Path)
    parser.add_argument("--allowlist", required=True, type=Path)
    parser.add_argument("--ca-cert", required=True, type=Path)
    parser.add_argument("--scorer-cert", required=True, type=Path)
    parser.add_argument("--scorer-key", required=True, type=Path)
    parser.add_argument("--evaluation-bank", required=True, type=Path)
    parser.add_argument("--public-directory", required=True, type=Path)
    parser.add_argument("--attempt", required=True, type=int)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--max-calls",
        type=int,
        default=int(os.environ.get("MAX_FIREWORKS_CALLS_PER_RUN", "105")),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = os.environ.get("FIREWORKS_API_KEY", "")
    if not api_key:
        print("error: FIREWORKS_API_KEY is required.", file=sys.stderr)
        return 1
    try:
        submission = verify_submission(
            submission_dir=args.submission_dir,
            allowlist_path=args.allowlist,
            tournament_ca_cert_path=args.ca_cert,
            scorer_private_key_path=args.scorer_key,
            scorer_cert_path=args.scorer_cert,
        )
        bank = load_evaluation_bank(
            args.evaluation_bank,
            public_directory=args.public_directory,
        )
        candidate_model, judge_model = _scoring_models()
        result = score_prompt(
            team_id=submission.team_id,
            attempt=args.attempt,
            run_id=args.run_id,
            participant_prompt=submission.prompt_text,
            cases=bank.cases,
            public_directory=args.public_directory,
            candidate_client=FireworksClient(
                api_key,
                model=candidate_model,
                empty_on_missing_content=True,
                on_retry=_log_retry,
            ),
            judge_client=FireworksClient(
                api_key,
                model=judge_model,
                on_retry=_log_retry,
            ),
            candidate_model=candidate_model,
            judge_model=judge_model,
            max_calls=args.max_calls,
            on_case_start=_log_progress,
        )
        _write_outputs(args.output, result)
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(_public_summary(result), sort_keys=True))
    return 0


def _write_outputs(output: Path, result: dict[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Scoring output directory must be empty.")
    _write_private_json(output / "summary.json", _public_summary(result))
    write_trace_bundle(result, output / "bundle")


def _public_summary(result: dict[str, Any]) -> dict[str, Any]:
    discovery = _aggregate_only(_required_object(result, "discovery"))
    holdout = _aggregate_only(_required_object(result, "holdout"))
    return {
        "schema_version": 1,
        "team_id": result["team_id"],
        "attempt": result["attempt"],
        "run_id": result["run_id"],
        "model": result["model"],
        "prompt_sha256": result["prompt_sha256"],
        "overall_score": result["overall_score"],
        "discovery": {
            "case_count": discovery["case_count"],
            "criteria": discovery["criteria"],
            "score": discovery["score"],
        },
        "holdout": holdout,
        "token_usage": _required_token_usage(result),
        "call_count": result["call_count"],
        "started_at": result["started_at"],
        "completed_at": result["completed_at"],
    }


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if os.name != "nt":
        path.chmod(0o600)


def _scoring_models() -> tuple[str, str]:
    return validate_scoring_models(
        os.environ.get("FIREWORKS_MODEL", ""),
        os.environ.get("JUDGE_MODEL", ""),
    )


def _aggregate_only(value: dict[str, object]) -> dict[str, object]:
    return {
        "case_count": _required_int(value, "case_count"),
        "criteria": _required_object(value, "criteria"),
        "score": _required_number(value, "score"),
    }


def _required_token_usage(value: dict[str, object]) -> dict[str, dict[str, int]]:
    token_usage = _required_object(value, "token_usage")
    return {
        bucket: {
            "prompt_tokens": _required_int(
                _required_object(token_usage, bucket), "prompt_tokens"
            ),
            "completion_tokens": _required_int(
                _required_object(token_usage, bucket), "completion_tokens"
            ),
            "total_tokens": _required_int(
                _required_object(token_usage, bucket), "total_tokens"
            ),
        }
        for bucket in ("candidate", "judge", "total")
    }


def _required_object(value: dict[str, object], key: str) -> dict[str, object]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise ValueError(f"Scoring result field {key} must be an object.")
    return cast(dict[str, object], item)


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


def _log_progress(current: int, total: int) -> None:
    print(f"Scoring case {current}/{total}.", file=sys.stderr, flush=True)


def _log_retry(current: int, total: int) -> None:
    print(
        f"Fireworks request was temporarily unavailable; retrying {current}/{total}.",
        file=sys.stderr,
        flush=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
