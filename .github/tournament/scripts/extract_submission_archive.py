from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hkpug_challenge.submission_archive import extract_submission_archive


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        extract_submission_archive(args.submission_archive, args.output)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
