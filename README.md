# HKPUG Public Challenge Package

Task 1 builds the public challenge dataset and the local validation contracts for
the HKPUG 14-day Opik production challenge.

## Included surfaces

- `public/cases.json`: versioned public case metadata
- `public/contexts/*.md`: the shared handbook plus ten domain evidence packs
- `src/hkpug_challenge/dataset.py`: `load_public_cases()`
- `src/hkpug_challenge/messages.py`: `SYSTEM_PROMPT` and `render_messages()`
- `src/hkpug_challenge/models.py`: `PublicCase`, `ChallengeAnswer`, and
  `validate_answer()`
- `starter/prompt.example.txt`: a participant-facing prompt starting point

## Local checks

```sh
uv run pytest tests/test_public_dataset.py -q
uv run ruff format --check .
uv run pyright
```
