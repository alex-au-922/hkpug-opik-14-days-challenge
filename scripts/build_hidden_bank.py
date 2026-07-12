from __future__ import annotations

import argparse
from pathlib import Path

from hkpug_challenge.hidden import build_hidden_bank


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate per-domain hidden variants and build one canonical hidden bank."
    )
    parser.add_argument(
        "--input",
        dest="input_directory",
        required=True,
        type=Path,
        help="Directory containing per-domain hidden bank JSON files.",
    )
    parser.add_argument(
        "--output",
        dest="output_path",
        required=True,
        type=Path,
        help="Canonical output path for the merged hidden bank JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build_hidden_bank(
        input_directory=args.input_directory,
        output_path=args.output_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
