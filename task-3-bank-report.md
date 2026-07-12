# Task 3 Bank Report

## Summary

The private evaluation bank now has a single canonical plaintext output at `.local/evaluation/evaluation_bank.json` under the authoritative repository root derived from the build script location.

Private cases are also constrained to the exact context-file combinations published for their domain in `public/cases.json`. Evidence IDs are still validated only from those selected files.

## Regression Coverage

- Arbitrary ignored output paths are rejected.
- CLI execution cannot bypass the trusted repository root.
- Nested Git repositories are rejected.
- Stray public files do not create valid private context combinations.
- Context combinations published for the wrong domain are rejected.

## Verification

- `uv run pytest tests/test_evaluation_bank.py -q`
- `uv run pytest -q`
- `uv run ruff check src/hkpug_challenge/evaluation_bank.py scripts/build_evaluation_bank.py tests/test_evaluation_bank.py`
- `uv run pyright src tests`
