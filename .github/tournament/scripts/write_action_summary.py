from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from hkpug_challenge.action_summary import render_action_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = cast(object, json.loads(args.summary.read_text(encoding="utf-8")))
    if not isinstance(payload, dict):
        raise ValueError("Scoring summary must be a JSON object.")
    summary = render_action_summary(cast(dict[str, object], payload))
    with args.output.open("a", encoding="utf-8") as output:
        output.write(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
