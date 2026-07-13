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
    return parser.parse_args()


def _authoritative_repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def main() -> int:
    args = parse_args()
    repository_root = _authoritative_repository_root()
    input_directory = (
        args.input_directory
        if args.input_directory.is_absolute()
        else repository_root / args.input_directory
    )
    build_evaluation_bank(
        input_directory=input_directory,
        output_path=repository_root / ".local" / "evaluation" / "evaluation_bank.json",
        repository_root=repository_root,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
