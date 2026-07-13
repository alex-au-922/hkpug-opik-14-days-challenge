# Discriminative Evaluation Bank Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite all 50 tournament evaluation cases so prompt quality produces meaningful score separation while every run stays below 500,000 total tokens.

**Architecture:** Keep the eleven public context documents unchanged and strengthen only the private case questions, references, and rubrics. Encode and validate one of five archetypes on every case, remove strategy from the fixed model wrapper, and aggregate actual Fireworks usage into a hard runtime budget check.

**Tech Stack:** Python 3.12, Pydantic, pytest, uv, Ruff, Pyright, JSON, OpenSSL CMS, GitHub Actions.

## Global Constraints

- Evaluate all 50 cases on every attempt: 40 discovery and 10 holdout.
- Preserve discovery difficulty counts 8 easy, 16 standard, 16 hard and holdout counts 2 easy, 4 standard, 4 hard.
- Preserve exactly one holdout case per domain and two holdout cases per archetype.
- Keep all files under `public/contexts/` byte-for-byte unchanged.
- Candidate plus judge prompt and completion usage must not exceed 500,000 tokens per run.
- Questions contain at most 80 words and references contain at most 100 words.
- Do not expose private questions, references, rubrics, or holdout details on participant-facing branches.

---

### Task 1: Enforce archetypes and token budget

**Files:**
- Modify: `.github/tournament/tests/test_evaluation_bank.py`
- Modify: `.github/tournament/tests/test_scoring.py`
- Modify: `.github/tournament/tests/test_scoring_configuration.py`
- Modify: `.github/tournament/src/hkpug_challenge/evaluation_bank.py`
- Modify: `.github/tournament/src/hkpug_challenge/scoring.py`
- Modify: `.github/tournament/src/hkpug_challenge/playground.py`

**Interfaces:**
- Produces `EvaluationCase.archetype: str` and `MAX_RUN_TOKENS = 500_000`.
- `score_prompt()` returns `token_usage` with candidate, judge, and total token counts.

- [ ] Add failing tests requiring all five archetypes once per domain, an 8:2 discovery/holdout split per archetype, 80-word question limits, a neutral fixed wrapper, usage aggregation, and rejection above 500,000 tokens.
- [ ] Run the focused tests and confirm failures identify the missing contracts.
- [ ] Implement the smallest schema, validation, wrapper, and usage changes that satisfy the tests.
- [ ] Run focused tests, then `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pyright`.

### Task 2: Rewrite ten domain banks in parallel

**Files:**
- Modify only: `.github/tournament/.local/evaluation/domains/*.json` in the authoritative local repository.

**Interfaces:**
- Each domain file contains five cases ordered by the five archetypes in the design specification.
- Existing case IDs, partitions, difficulties, context file paths, and evidence IDs remain valid.

- [ ] Assign account access/API limits, billing/data retention, integrations/privacy, refunds/security, and service incidents/subscriptions to five workers with disjoint files.
- [ ] Require every worker to preserve context files and token caps while replacing questions, references, key points, required citation groups, required points, prohibited claims, and non-authoritative evidence.
- [ ] Review every returned file for direct answer leakage, invalid evidence IDs, duplicated scenarios, unsupported reference claims, and archetype compliance.
- [ ] Run the evaluation-bank builder and focused validation tests.

### Task 3: Build and encrypt the private bank

**Files:**
- Regenerate locally: `.github/tournament/.local/evaluation/evaluation_bank.json`
- Modify: `.github/tournament/evaluation_bank.json.cms`

**Interfaces:**
- The canonical JSON is local and ignored.
- Only the CMS-encrypted bank is tracked for production scoring.

- [ ] Build the canonical bank with `.github/tournament/scripts/build_evaluation_bank.py`.
- [ ] Verify 50 unique cases, the required partition/difficulty/archetype matrices, valid evidence IDs, and bounded text.
- [ ] Encrypt the canonical bank to the scorer certificate and validate a round trip with the scorer private key.
- [ ] Run the full test and static-check suite.

### Task 4: Recalibrate production scoring

**Files:**
- Read-only calibration prompts: `.local/calibration/prompts/attempt-01.txt` through `attempt-04.txt`.
- Generated encrypted submissions and private feedback artifacts only.

**Interfaces:**
- Four sequential submissions use the same cumulative prompt ladder as the approved calibration design.
- Every report records overall, discovery, holdout, criteria, and actual total token usage.

- [ ] Publish the organizer commit and update `ORGANIZER_REF` on the participant workflow.
- [ ] Run four sequential organizer-test submissions through the real candidate and judge models.
- [ ] Confirm every run uses at most 425,000 tokens, retaining 15% headroom below 500,000.
- [ ] Confirm the basic prompt no longer saturates the bank and useful strategies create material, though not forced-monotonic, separation.
- [ ] Clear organizer-test events and leaderboard data after recording the calibration results.
