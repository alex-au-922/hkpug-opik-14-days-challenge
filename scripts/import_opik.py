from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from hkpug_challenge.opik_replay import (
    DEFAULT_BASE_URL,
    OpikReplayError,
    ReplayConfig,
    replay_bundle,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import a decrypted discovery feedback bundle into Opik."
    )
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--workspace")
    parser.add_argument("--project-name")
    parser.add_argument(
        "--basic-username", default=os.environ.get("OPIK_BASIC_AUTH_USERNAME")
    )
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--retry-delay-seconds", type=float, default=0.25)
    parser.add_argument("--timeout-seconds", type=float, default=30)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = replay_bundle(
            args.bundle,
            ReplayConfig(
                base_url=args.base_url,
                workspace=args.workspace,
                project_name=args.project_name,
                bearer_token=os.environ.get("OPIK_API_KEY") or None,
                basic_username=args.basic_username,
                basic_password=os.environ.get("OPIK_BASIC_AUTH_PASSWORD") or None,
                max_retries=args.max_retries,
                retry_delay_seconds=args.retry_delay_seconds,
                timeout_seconds=args.timeout_seconds,
            ),
        )
    except (OpikReplayError, ValueError) as exc:
        print(f"import_opik.py: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
