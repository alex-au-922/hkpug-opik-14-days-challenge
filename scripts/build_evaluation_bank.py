from __future__ import annotations

import argparse
from pathlib import Path

from hkpug_challenge.evaluation_bank import build_evaluation_bank


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate per-domain evaluation cases and build one canonical evaluation bank."
    )
    parser.add_argument(
        "--input",
        dest="input_directory",
        required=True,
        type=Path,
        help="Directory containing per-domain evaluation bank JSON files.",
    )
    parser.add_argument(
        "--output",
        dest="output_path",
        required=True,
        type=Path,
        help="Canonical output path for the merged evaluation bank JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build_evaluation_bank(
        input_directory=args.input_directory,
        output_path=args.output_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
