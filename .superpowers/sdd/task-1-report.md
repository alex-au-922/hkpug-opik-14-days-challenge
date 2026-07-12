# Task 1 Report

Date: 2026-07-12

## Scope

Implemented Task 1 in `/Users/alexau/Project/hkpug-opik-14-days-challenge` only:

- `pyproject.toml`
- `.python-version`
- `.gitignore`
- `README.md`
- `src/hkpug_challenge/__init__.py`
- `src/hkpug_challenge/models.py`
- `src/hkpug_challenge/dataset.py`
- `src/hkpug_challenge/messages.py`
- `public/cases.json`
- `public/contexts/*.md`
- `starter/prompt.example.txt`
- `tests/test_public_dataset.py`

## TDD Record

### Red

Command:

```sh
uv run pytest tests/test_public_dataset.py -q
```

Observed output:

```text
==================================== ERRORS ====================================
________________ ERROR collecting tests/test_public_dataset.py _________________
ImportError while importing test module '/Users/alexau/Project/hkpug-opik-14-days-challenge/tests/test_public_dataset.py'.
...
E   ModuleNotFoundError: No module named 'hkpug_challenge'
=========================== short test summary info ============================
ERROR tests/test_public_dataset.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.05s
```

Result: expected missing-package failure before implementation.

### Green

Command:

```sh
uv run pytest tests/test_public_dataset.py -q
```

Observed output:

```text
.............                                                            [100%]
13 passed in 0.36s
```

## Verification

Command:

```sh
uv run pytest tests/test_public_dataset.py -q
```

Observed output:

```text
.............                                                            [100%]
13 passed in 0.09s
```

Command:

```sh
uv run ruff format --check .
```

Observed output:

```text
5 files already formatted
```

Command:

```sh
uv run pyright
```

Observed output:

```text
0 errors, 0 warnings, 0 informations
```

## Public Dataset Notes

- Loaded case count: `50`
- Average estimated context tokens: `4503.30`
- Preserved 10 domains with 5 public cases each
- Preserved 10 easy / 30 standard / 10 hard difficulty balance
- Applied the resolved QA wording to `REF-02`, `REF-05`, `SUB-04`, `ACC-04`, `SEC-03`, `INT-01`, and `INT-04`

## Implementation Summary

- Ported the public evidence packs from the draft source repo without modifying the source repo.
- Added a typed public package with frozen dataclasses for `PublicCase` and `ChallengeAnswer`.
- Used Pydantic at the JSON-validation boundary for case loading and answer validation.
- Enforced rejection of path escapes, missing fields, extra fields, duplicate citations, unknown citations, non-boolean escalation, and answers over 100 words.
- Added dataset and contract tests that lock the public balance, token budget, and resolved QA wording.
