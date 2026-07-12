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
