# Task 2 Report

Date: 2026-07-12

## Scope

Implement Task 2 in `/Users/alexau/Project/hkpug-opik-14-days-challenge` only:

- `.gitignore`
- `pyproject.toml`
- `uv.lock`
- `README.md`
- `src/hkpug_challenge/__init__.py`
- `src/hkpug_challenge/submission.py`
- `submission/prompt.example.txt`
- `submission/manifest.example.json`
- `submission/encrypt_prompt.sh`
- `scripts/verify_submission.py`
- `tests/test_submission.py`
- `.github/tournament/team_allowlist.json`
- `.github/tournament/public_keys/tournament_ca_cert.pem`
- `.github/tournament/public_keys/scorer_cert.pem`
- `.github/tournament/public_keys/organizer-test_cert.pem`

## TDD Record

### Red

Command:

```sh
uv run pytest tests/test_submission.py -q
```

Observed output:

```text
==================================== ERRORS ====================================
__________________ ERROR collecting tests/test_submission.py ___________________
ImportError while importing test module '/Users/alexau/Project/hkpug-opik-14-days-challenge/tests/test_submission.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
../../.local/share/uv/python/cpython-3.10.19-macos-aarch64-none/lib/python3.10/importlib/__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests/test_submission.py:11: in <module>
    from hkpug_challenge.submission import verify_submission
E   ModuleNotFoundError: No module named 'hkpug_challenge.submission'
=========================== short test summary info ============================
ERROR tests/test_submission.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.12s
```

Result: expected missing Task 2 implementation before production code.

### Green

Command:

```sh
uv run pytest tests/test_submission.py -q
```

Observed output:

```text
......                                                                  [100%]
7 passed in 3.58s
```

## Verification

Command:

```sh
uv run pytest tests/test_submission.py -q
```

Observed output:

```text
......                                                                  [100%]
7 passed in 3.77s
```

Command:

```sh
uv run pytest -q
```

Observed output:

```text
.....................                                                    [100%]
21 passed in 3.72s
```

Command:

```sh
uv run ruff format --check .
```

Observed output:

```text
8 files already formatted
```

Command:

```sh
uv run pyright
```

Observed output:

```text
0 errors, 0 warnings, 0 informations
```

Command:

```sh
openssl verify -CAfile .github/tournament/public_keys/tournament_ca_cert.pem \
  .github/tournament/public_keys/scorer_cert.pem \
  .github/tournament/public_keys/organizer-test_cert.pem
```

Observed output:

```text
.github/tournament/public_keys/scorer_cert.pem: OK
.github/tournament/public_keys/organizer-test_cert.pem: OK
```

Command:

```sh
if git grep -n "BEGIN .*PRIVATE KEY" -- . ':(exclude).local'; then
  echo 'Tracked private key marker found.'
  exit 1
else
  echo 'No tracked private key markers found.'
fi
```

Observed output:

```text
No tracked private key markers found.
```

Command:

```sh
if git ls-files | rg '(^|/)(\.local/|submission/prompt\.txt$)'; then
  echo 'Tracked ignored secret/plaintext path found.'
  exit 1
else
  echo 'No ignored secret/plaintext paths are tracked.'
fi
```

Observed output:

```text
No ignored secret/plaintext paths are tracked.
```

## Implementation Summary

- Added `src/hkpug_challenge/submission.py` with strict manifest validation,
  canonical JSON emission, RSA manifest signing, AES-256-CBC DER CMS inspection,
  allowlist-driven certificate verification, trusted scorer decryption, and
  prompt SHA-256 enforcement.
- Added `submission/encrypt_prompt.sh` and `scripts/verify_submission.py` as the
  participant and trusted verifier entry points.
- Added end-to-end crypto tests that mint temporary CA, scorer, and team
  certificates and prove valid verification plus tamper failures for ciphertext,
  manifest shape, signature, team identity, and prompt path.
- Generated a real local tournament CA, scorer key/cert, and organizer-test team
  key/cert with private keys only under ignored `.local/`.
- Tracked the tournament CA cert, scorer cert, organizer-test cert, and an
  allowlist entry pinned to the organizer-test certificate fingerprint.

## Security Review Fix

Date: 2026-07-12

### Red

Command:

```sh
uv run pytest tests/test_submission.py -q
```

Observed result after adding the security-review regressions:

```text
24 failed, 8 passed in 18.15s
```

The failures covered missing trusted scorer CMS recipient checks, multiple CMS
recipient acceptance, missing scorer certificate chain/validity/identity/key
usage checks, unbounded pre-read file handling, symlink acceptance, traceback
CLI errors, and group/world-readable private key acceptance.

### Green

Command:

```sh
uv run pytest tests/test_submission.py -q
```

Observed output:

```text
................................                                         [100%]
32 passed in 18.58s
```

### Implementation Summary

- Split the former 603-line `src/hkpug_challenge/submission.py` into:
  `submission_manifest.py` for manifest/canonical JSON and allowlist loading,
  `submission_crypto.py` for certificate/CMS/OpenSSL/private-key handling, and a
  thinner `submission.py` orchestration/CLI module with compatibility exports.
- Added bounded regular-file reads before consuming manifests, signatures,
  allowlists, certificates, ciphertext, prompt text, and private keys. Symlinks
  are rejected before final-path reads.
- Validates tournament CA properties, certificate validity windows, leaf
  non-CA status, scorer identity `HKPUG Scorer`, scorer key encipherment, team
  identity/key usage, and CA signatures before CMS decrypt.
- Parses DER CMS metadata to require exactly one recipient whose issuer/serial
  matches the trusted scorer certificate and requires AES-256-CBC.
- Decrypts CMS to a temporary file, size-checks plaintext at 8192 bytes before
  reading, and no longer captures plaintext from stdout.
- Rejects group/world-readable private key files on POSIX mode platforms.
- CLI validation failures now print concise `error: ...` messages without
  Python tracebacks.

### Verification

Commands that passed:

```sh
uv run pytest tests/test_submission.py -q
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run ruff format --check src/hkpug_challenge/submission.py src/hkpug_challenge/submission_crypto.py src/hkpug_challenge/submission_manifest.py tests/test_submission.py
uv run pyright
uv run pyright src/hkpug_challenge/submission.py src/hkpug_challenge/submission_crypto.py src/hkpug_challenge/submission_manifest.py tests/test_submission.py
openssl verify -CAfile .github/tournament/public_keys/tournament_ca_cert.pem .github/tournament/public_keys/scorer_cert.pem .github/tournament/public_keys/organizer-test_cert.pem
git grep -n "BEGIN .*PRIVATE KEY" -- . ':(exclude).local' ':(exclude).superpowers/sdd/task-2-report.md'
git ls-files | rg '(^|/)(\.local/|submission/prompt\.txt$)'
```

Observed highlights:

```text
32 passed in 18.58s
54 passed in 18.11s
All checks passed!
13 files already formatted
0 errors, 0 warnings, 0 informations
.github/tournament/public_keys/scorer_cert.pem: OK
.github/tournament/public_keys/organizer-test_cert.pem: OK
```

The two `git grep`/`git ls-files | rg` scans produced no matches after excluding
the report text that documents the private-key scan command.
