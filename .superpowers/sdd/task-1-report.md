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

## Review Wording Adjustment

Date: 2026-07-12

### Red

Updated the reviewed-case expectations for `SUB-04`, `INT-04`, and `SEC-03`
to the tightened wording, then ran:

```sh
uv run pytest tests/test_public_dataset.py::test_reviewed_cases_use_deterministic_single_decision_questions -q
```

Observed output:

```text
F                                                                        [100%]
=================================== FAILURES ===================================
_______ test_reviewed_cases_use_deterministic_single_decision_questions ________
...
E       AssertionError: assert {'INT-04': 'T...be restored?'} == {'INT-04': 'T...enewal date?'}
=========================== short test summary info ============================
FAILED tests/test_public_dataset.py::test_reviewed_cases_use_deterministic_single_decision_questions
1 failed in 0.07s
```

Result: expected failure while `public/cases.json` still held the earlier
question text.

### Fix

- `SUB-04` now asks only whether Incident Command may restore the prior renewal
  date after a pre-expiry reversal was blocked by the confirmed billing-portal
  incident and the request landed within seven days of expiry.
- `INT-04` now asks only which connector state applies after the shared field
  changed in both systems inside the same two-minute sync window.
- `SEC-03` now removes the personal-data reference and asks only for immediate
  credential handling before Product Security review.
- The reviewed-case regression test keeps exact full-string comparisons for all
  four cases.

### Green

Command:

```sh
uv run pytest tests/test_public_dataset.py::test_reviewed_cases_use_deterministic_single_decision_questions -q
```

Observed output:

```text
.                                                                        [100%]
1 passed in 0.05s
```

Command:

```sh
uv run pytest tests/test_public_dataset.py -q
```

Observed output:

```text
..............                                                           [100%]
14 passed in 0.08s
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

## Important Review Fixes

Date: 2026-07-12

### Root Cause

The original QA regression test asserted only isolated substrings. Those checks
allowed the four cases to retain compound or unrelated decisions even though the
required facts were present.

### Red

Added an exact full-question mapping for `REF-02`, `SUB-04`, `INT-04`, and
`SEC-03`, then ran:

```sh
uv run pytest tests/test_public_dataset.py::test_reviewed_cases_use_deterministic_single_decision_questions -vv
```

Observed output:

```text
collected 1 item
tests/test_public_dataset.py::test_reviewed_cases_use_deterministic_single_decision_questions FAILED [100%]
E       AssertionError: assert { ... old REF-02, SUB-04, INT-04, SEC-03 questions ... }
E       == { ... reviewed REF-02, SUB-04, INT-04, SEC-03 questions ... }
============================== 1 failed in 0.07s ===============================
```

Result: expected failure because all four stored questions differed from the
deterministic reviewed wording.

### Fix

- `REF-02` now asks only which charge should be refunded after identifying one
  valid subscription purchase and one additional settled duplicate caused by
  `PAY-2026-0512`.
- `SUB-04` now asks only whether the prior renewal date may be restored after a
  confirmed incident prevented a pre-expiry reversal and the request arrived
  within seven calendar days. The credit question was removed.
- `INT-04` now identifies `renewal_contact_email` as customer-configurable,
  records changes in both systems within the same two-minute window, and asks
  only for the connector state and resolution decision.
- `SEC-03` now asks only for immediate handling of live access tokens before
  Product Security review. Personal-data routing was removed.
- The regression test compares the complete question strings for all four
  cases instead of checking loose substrings.

### Green

Command:

```sh
uv run pytest tests/test_public_dataset.py::test_reviewed_cases_use_deterministic_single_decision_questions -q
```

Observed output:

```text
.                                                                        [100%]
1 passed in 0.05s
```

### Fix Verification

Command:

```sh
uv run pytest tests/test_public_dataset.py -q
```

Observed output:

```text
..............                                                           [100%]
14 passed in 0.08s
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
