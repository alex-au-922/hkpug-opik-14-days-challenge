# Task 2 TOCTOU Closure Report

Date: 2026-07-12

## Scope

Owned files:

- `src/hkpug_challenge/submission_manifest.py`
- `src/hkpug_challenge/submission_crypto.py`
- `src/hkpug_challenge/submission.py`
- `tests/test_submission.py`
- `task-2-report.md`

Hidden bank and plan files were not modified by this work.

## Red Tests Added

- `test_read_bounded_regular_file_uses_open_descriptor_after_metadata_check`
  failed before the fix because a path replacement after metadata inspection was
  read through the path.
- `test_read_bounded_regular_file_rejects_growth_after_metadata_check` failed
  before the fix because over-limit data added after the initial size check was
  accepted.
- `test_verify_submission_uses_same_ciphertext_bytes_for_inspection_and_decryption`
  failed before the fix because ciphertext swapped after ASN.1 inspection was
  reopened and decrypted.

Red command:

```bash
uv run pytest tests/test_submission.py -q -k 'open_descriptor_after_metadata_check or growth_after_metadata_check or same_ciphertext_bytes'
```

Initial result: `3 failed, 36 deselected`.

## Fix Summary

- Replaced path `lstat` plus `Path.read_bytes()` with descriptor-anchored
  reading: `os.open(..., O_RDONLY | O_NOFOLLOW)`, `os.fstat()`, regular-file
  and size validation, and a bounded read of at most `limit + 1` bytes from the
  same descriptor.
- Fail closed when `os.O_NOFOLLOW` is unavailable with an actionable
  Linux/macOS/WSL requirement for untrusted verification.
- Re-check size after the descriptor read so files that grow after `fstat()` are
  rejected.
- Changed `verify_submission` to snapshot ciphertext exactly once and pass the
  same immutable bytes to ASN.1 inspection and OpenSSL decryption.
- Changed OpenSSL decryption to consume already-read ciphertext, scorer
  certificate, and scorer private-key bytes, then write private temporary
  snapshots from those exact bytes.
- Checked scorer private-key mode from the same descriptor snapshot used for
  the key bytes.

## Verification

```bash
uv run pytest tests/test_submission.py -q -k 'open_descriptor_after_metadata_check or growth_after_metadata_check or same_ciphertext_bytes'
```

Result: `3 passed, 36 deselected`.

```bash
uv run pytest tests/test_submission.py -q
```

Result: `39 passed`.

```bash
uv run pytest -q
```

Result: `65 passed`.

Later final rerun note: after unrelated workspace changes appeared outside this
task's owned files, `uv run pytest -q` was blocked during collection by
`tests/test_evaluation_bank.py` importing missing `EvaluationBank`. The same
unowned file also blocked repository-wide `uv run ruff format --check .`.
Owned-file verification still passed:

```bash
uv run pytest tests/test_submission.py -q
uv run ruff format --check src/hkpug_challenge/submission_manifest.py src/hkpug_challenge/submission_crypto.py src/hkpug_challenge/submission.py tests/test_submission.py
uv run ruff check src/hkpug_challenge/submission_manifest.py src/hkpug_challenge/submission_crypto.py src/hkpug_challenge/submission.py tests/test_submission.py
uv run pyright src/hkpug_challenge/submission_manifest.py src/hkpug_challenge/submission_crypto.py src/hkpug_challenge/submission.py tests/test_submission.py
```

Results:

- `39 passed`
- `4 files already formatted`
- `All checks passed!`
- `0 errors, 0 warnings, 0 informations`

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
```

Results:

- `13 files already formatted`
- `All checks passed!`
- `0 errors, 0 warnings, 0 informations`

## Cert and Secret Scans

Private-key block scan:

```bash
git grep -n -E -e '-----BEGIN ((RSA|EC|OPENSSH|DSA) )?PRIVATE KEY-----|-----BEGIN ENCRYPTED PRIVATE KEY-----' -- ':!src/hkpug_challenge/hidden.py' ':!tests/test_hidden_bank.py' ':!docs/superpowers/plans/*'
```

Result: no matches.

Public certificate block scan:

```bash
git grep -n -E -e '-----BEGIN CERTIFICATE-----' -- ':!src/hkpug_challenge/hidden.py' ':!tests/test_hidden_bank.py' ':!docs/superpowers/plans/*'
```

Result: only expected public tournament certificates:

- `.github/tournament/public_keys/organizer-test_cert.pem`
- `.github/tournament/public_keys/scorer_cert.pem`
- `.github/tournament/public_keys/tournament_ca_cert.pem`

Certificate subject/issuer check:

```bash
for cert in .github/tournament/public_keys/*.pem; do openssl x509 -in "$cert" -noout -subject -issuer; done
```

Result:

- `subject=CN=organizer-test`, `issuer=CN=HKPUG Tournament CA`
- `subject=CN=HKPUG Scorer`, `issuer=CN=HKPUG Tournament CA`
- `subject=CN=HKPUG Tournament CA`, `issuer=CN=HKPUG Tournament CA`

High-confidence token pattern scan:

```bash
git grep -n -i -E -e '(AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9_]{36,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{32,}|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[A-Za-z0-9_-]{35})' -- ':!src/hkpug_challenge/hidden.py' ':!tests/test_hidden_bank.py' ':!docs/superpowers/plans/*' ':!uv.lock'
```

Result: no matches.
