# Task 3 Evaluation Bank Report

Status: DONE

## Scope Delivered

- Replaced the superseded hidden-bank package surface with `src/hkpug_challenge/evaluation_bank.py`.
- Replaced the merge CLI with `scripts/build_evaluation_bank.py`.
- Replaced TDD coverage with `tests/test_evaluation_bank.py`.
- Updated package exports in `src/hkpug_challenge/__init__.py`.
- Updated `docs/qa/question-review.md` to describe the two-human-review semantic gate for private references and rubrics.

## Guardrails Preserved

- Root schema fields are exactly `schema_version`, `dataset_version`, `rubric_version`, and `cases`.
- Private cases are fixed records with `case_id`, `partition`, `domain`, `difficulty`, `question`, `context_files`, `reference`, and `rubric`.
- Validation enforces exactly 50 cases, 40 discovery, 10 holdout, five per domain, one holdout per domain, and the 10/30/10 difficulty mix.
- Validation rejects duplicate IDs, duplicate question text, question text reused from public practice cases, unknown context files, unknown evidence IDs, overly long reference answers, and extra fields.
- The old attempt-assignment and variant rotation API surface was removed.
- Safe output writing still uses the reviewed `git check-ignore -v --non-matching --no-index` gate for `.local`, rejects nested repositories, opens the final file with descriptor-anchored `O_NOFOLLOW`, verifies a regular file target, and forces mode `0600`.
- The canonical plaintext output is fixed to `.local/evaluation/evaluation_bank.json` under the repository root derived from the trusted build-script location.
- Private cases must use an exact context-file combination published for the same domain in `public/cases.json`; arbitrary public files and cross-domain combinations are rejected.

## Verification

- Red: `uv run pytest tests/test_evaluation_bank.py -q` failed with `ImportError: cannot import name 'EvaluationBank' from 'hkpug_challenge'`
- Green: `uv run pytest tests/test_evaluation_bank.py -q`
- Green: `uv run pytest -q`
- Green: `uv run ruff check src/hkpug_challenge/evaluation_bank.py scripts/build_evaluation_bank.py tests/test_evaluation_bank.py`
- Green: `uv run pyright src tests`

## Not Included

- No crypto files were changed.
- No plaintext private evaluation cases were added to the repository.
