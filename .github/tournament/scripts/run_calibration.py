from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from hkpug_challenge.calibration import run_calibration
from hkpug_challenge.evaluation_bank import load_evaluation_bank
from hkpug_challenge.fireworks import FireworksClient, validate_scoring_models


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation-bank", required=True, type=Path)
    parser.add_argument("--public-directory", required=True, type=Path)
    parser.add_argument("--prompt-directory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = os.environ.get("FIREWORKS_API_KEY", "")
    if not api_key:
        print("error: FIREWORKS_API_KEY is required.", file=sys.stderr)
        return 1

    try:
        candidate_model, judge_model = _scoring_models()
        bank = load_evaluation_bank(
            args.evaluation_bank,
            public_directory=args.public_directory,
        )
        result = run_calibration(
            bank=bank,
            prompt_directory=args.prompt_directory,
            public_directory=args.public_directory,
            output_path=args.output,
            candidate_client=FireworksClient(
                api_key,
                model=candidate_model,
                on_retry=_log_retry,
            ),
            judge_client=FireworksClient(
                api_key,
                model=judge_model,
                on_retry=_log_retry,
            ),
            candidate_model=candidate_model,
            judge_model=judge_model,
            on_progress=_log_progress,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "output": str(args.output),
                "passed": result.passed,
                "gates": {gate.name: gate.passed for gate in result.gates},
            },
            sort_keys=True,
        )
    )
    return 0


def _scoring_models() -> tuple[str, str]:
    return validate_scoring_models(
        os.environ.get("FIREWORKS_MODEL", ""),
        os.environ.get("JUDGE_MODEL", ""),
    )


def _log_progress(profile: str, current: int, total: int) -> None:
    print(
        f"Calibration {profile}: case {current}/{total}.",
        file=sys.stderr,
        flush=True,
    )


def _log_retry(current: int, total: int) -> None:
    print(
        f"Fireworks request was temporarily unavailable; retrying {current}/{total}.",
        file=sys.stderr,
        flush=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
