from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

from hkpug_challenge.pr_validation import validate_pr_files
from hkpug_challenge.submission_manifest import read_bounded_regular_file


MAX_PR_FILES_BYTES = 64 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files-json", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        payload = cast(
            object,
            json.loads(
                read_bounded_regular_file(
                    args.files_json,
                    "Pull request files",
                    MAX_PR_FILES_BYTES,
                )
            ),
        )
        paths = validate_pr_files(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"validated_paths": paths}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
