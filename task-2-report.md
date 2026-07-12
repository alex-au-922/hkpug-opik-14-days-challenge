## Task 2 Review Fixes - 2026-07-12

- Replaced OpenSSL CMS text inspection with DER CMS parsing via `asn1crypto`.
- Enforced exactly one total `recipientInfo`, rejected non-KTRI recipient types, required `issuerAndSerialNumber`, compared issuer DER plus serial to the trusted scorer certificate, and required parsed `aes256_cbc`.
- Removed the ciphertext/key/cert TOCTOU window for OpenSSL decryption by reading bounded regular non-symlink inputs first, writing exact-byte snapshots into a private temporary directory with `0600` files, and invoking OpenSSL only on those snapshots.
- Normalized malformed and encrypted team private-key load failures, including `TypeError`, to concise CLI `ValueError` output.
- Added regressions for mixed scorer KTRI plus EC key-agreement recipient, OpenSSL snapshot observation, and malformed/encrypted private-key CLI behavior.

Verification:

- Red run before fix: `uv run pytest tests/test_submission.py -k "snapshots_to_decryption or scorer_ktri_plus_key_agreement_recipient or invalid_private_key_without_traceback"` failed on mixed-recipient acceptance, original OpenSSL path use, and encrypted-key traceback.
- Focused green run: same command passed, `4 passed`.
- Narrow suite: `uv run pytest tests/test_submission.py` passed, `36 passed`.
- Full tests: `uv run pytest -q` passed, `62 passed`.
- Lint: `uv run ruff check .` passed.
- Format: `uv run ruff format --check src/hkpug_challenge/submission_crypto.py tests/test_submission.py` passed. Full `uv run ruff format --check .` still reports pre-existing hidden-bank formatting drift in `src/hkpug_challenge/hidden.py` and `tests/test_hidden_bank.py`; those files were intentionally not touched.
- Types: `uv run pyright` passed, `0 errors`.
- Cert verify: `openssl verify -CAfile .github/tournament/public_keys/tournament_ca_cert.pem .github/tournament/public_keys/scorer_cert.pem .github/tournament/public_keys/organizer-test_cert.pem` and CA self-verify passed.
- Secret scan: tracked-file scan for common private key/API token patterns returned no matches.
- Path scan: touched-file scan found no hidden-bank references; broader touched-file private path scan found only the expected scorer private-key default/test fixture paths.
