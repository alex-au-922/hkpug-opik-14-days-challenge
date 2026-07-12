# Task 3 Schema Report

Status: DONE

## Scope Delivered

- Added hidden-bank schema/runtime foundation in `src/hkpug_challenge/hidden.py`.
- Added deterministic per-team/per-family slot rotation for attempts 1 through 8 using SHA-256.
- Added canonical merge/build CLI in `scripts/build_hidden_bank.py`.
- Added synthetic TDD coverage in `tests/test_hidden_bank.py`.
- Added the initial human fairness review scaffold in `docs/qa/question-review.md`.
- Exported the hidden-bank package surface from `src/hkpug_challenge/__init__.py`.

## Guardrails Implemented

- Root schema fields are exactly `schema_version`, `dataset_version`, `rubric_version`, and `variants`.
- Variant validation enforces `variant_id`, `family_id`, slots `1..8`, `domain`, `difficulty`, `archetype`, `question`, `context_files`, `reference`, and `rubric`.
- Reference validation enforces non-empty answers capped at 100 words, citations, boolean escalation, and key points.
- Rubric validation supports `required_citation_groups`, `required_points`, `prohibited_claims`, and `non_authoritative_evidence` without a blanket forbidden-citation rule.
- Syntactic validators prove field presence and type; human review proves semantic correctness and non-authoritative status.
- Hidden-bank validation enforces:
  - 400 variants total
  - 8 variants per family
  - slots `1..8` exactly once per family
  - 50 assigned variants per attempt
  - 10/30/10 difficulty balance per attempt
  - existing public families, domains, difficulties, and context files
  - known evidence IDs for reference/rubric citations
  - disjoint family and variant IDs
  - unique question text
  - no undisclosed context
- `reference.escalate` is preserved as the authoritative escalation state in the typed model, canonical JSON, and assigned variants.
- Canonical writer sets file mode `0600` and rejects symlinks, non-regular targets, and unsafe final-component races.
- Build output is refused unless the exact path is ignored by the authoritative Git repository with `git check-ignore --no-index`.

## Verification

- `uv run pytest tests/test_hidden_bank.py -q`
- `uv run pytest -q`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pyright`

## Not Included Yet

- No real hidden variants
- No encrypted hidden bank artifact
- No submission/crypto file changes

## Concerns

- None for the schema/validator foundation in this scope.
