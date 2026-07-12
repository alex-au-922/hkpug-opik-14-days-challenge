# HKPUG Challenge Package

Tasks 1 and 2 build the public challenge dataset, local answer validation
contracts, and the encrypted prompt submission workflow for the HKPUG 14-day
Opik production challenge.

## Included surfaces

- `public/cases.json`: versioned public case metadata
- `public/contexts/*.md`: the shared handbook plus ten domain evidence packs
- `src/hkpug_challenge/dataset.py`: `load_public_cases()`
- `src/hkpug_challenge/messages.py`: `SYSTEM_PROMPT` and `render_messages()`
- `src/hkpug_challenge/models.py`: `PublicCase`, `ChallengeAnswer`, and
  `validate_answer()`
- `src/hkpug_challenge/submission.py`: canonical manifest creation, manifest
  signing, and trusted submission verification
- `starter/prompt.example.txt`: a participant-facing prompt starting point
- `submission/prompt.example.txt`: example participant prompt text
- `submission/manifest.example.json`: canonical example manifest
- `submission/encrypt_prompt.sh`: local prompt encryption and signing helper
- `scripts/verify_submission.py`: trusted verifier CLI
- `.github/tournament/public_keys/*.pem`: tracked tournament public certificates
- `.github/tournament/team_allowlist.json`: tracked team certificate allowlist

## Local checks

```sh
uv run pytest tests/test_submission.py -q
uv run pytest tests/test_public_dataset.py -q
uv run pytest -q
uv run ruff format --check .
uv run pyright
```
