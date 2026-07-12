from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from hkpug_challenge.dataset import load_public_cases
from hkpug_challenge.fireworks import FireworksClient
from hkpug_challenge.playground import PlaygroundCase, run_playground
from hkpug_challenge.submission import load_prompt_text


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROMPT_PATH = REPOSITORY_ROOT / "starter" / "prompt.example.txt"
DEFAULT_OUTPUT_PATH = REPOSITORY_ROOT / ".local" / "playground" / "run.json"
CASE_INDEXES = (0, 5, 10)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a small real-model discovery/holdout tournament proof."
    )
    parser.add_argument("--prompt-path", type=Path, default=DEFAULT_PROMPT_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = os.environ.get("FIREWORKS_API_KEY", "")
    if not api_key:
        raise SystemExit("FIREWORKS_API_KEY is required.")

    public_cases = load_public_cases()
    selected = tuple(public_cases[index] for index in CASE_INDEXES)
    playground_cases = (
        PlaygroundCase(selected[0], "discovery"),
        PlaygroundCase(selected[1], "discovery"),
        PlaygroundCase(selected[2], "holdout"),
    )
    result = run_playground(
        system_prompt=load_prompt_text(args.prompt_path),
        cases=playground_cases,
        client=FireworksClient(api_key),
    )

    output_path = args.output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        output_path.chmod(0o600)
    print(
        json.dumps(
            {
                "overall_score": result["overall_score"],
                "discovery_score": result["discovery"]["score"],
                "holdout_score": result["holdout"]["score"],
                "call_count": result["call_count"],
                "output_path": str(output_path),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
