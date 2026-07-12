# HKPUG 14-Day Opik Challenge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a production GitHub tournament where teams submit encrypted prompts, receive eight hidden DeepSeek V4 Flash evaluations with encrypted Opik-compatible feedback, and follow scores on a live GitHub Pages dashboard.

**Architecture:** An untrusted pull-request workflow validates a CMS-encrypted prompt and team-signed manifest without secrets. A separate trusted `workflow_run` decrypts only prompt text and a frozen hidden suite, calls Fireworks, builds portable Opik REST payloads, encrypts the feedback bundle to the submitting team, updates an append-only leaderboard, and deploys static Pages. Public cases and local tooling teach the task; hidden variants, reference rubrics, decrypted prompts, and expected answers never enter logs or public artifacts.

**Tech Stack:** Python 3.10+, `uv`, `pydantic`, `pytest`, Fireworks OpenAI-compatible HTTP API, OpenSSL CMS/RSA signatures, Opik private REST payloads, GitHub Actions, GitHub Pages, static HTML/CSS/JavaScript

## Global Constraints

- Exactly 50 public case families across ten support domains.
- Exactly eight total official scored attempts per team, idempotent by signed submission identity.
- Use `accounts/fireworks/models/deepseek-v4-flash` for participant answers.
- Never commit Fireworks credentials, private keys, plaintext hidden cases, reference answers, or plaintext participant prompts.
- Never execute participant-controlled code in any workflow, especially a secret-bearing workflow.
- Only `submission/prompt.txt.cms`, `submission/manifest.json`, and `submission/manifest.sig` may change in a scoring PR.
- Every scored attempt emits an encrypted, team-readable Opik replay bundle and public aggregate scores without hidden answers.
- Human participants must be able to understand every public case from supplied evidence; no answer may depend on agent-only discovery, trivia, or undisclosed conventions.
- All scoring inputs, model settings, rubric versions, and suite assignments are frozen and reproducible.
- The public dashboard reports team best score, latest score, attempt count, run history, and criterion breakdown without exposing prompts or hidden cases.

---

### Task 1: Public Challenge Package And Contracts

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `.gitignore`
- Create: `README.md`
- Create: `src/hkpug_challenge/models.py`
- Create: `src/hkpug_challenge/dataset.py`
- Create: `src/hkpug_challenge/messages.py`
- Create: `public/cases.json`
- Create: `public/contexts/*.md`
- Create: `starter/prompt.example.txt`
- Create: `tests/test_public_dataset.py`

**Interfaces:**
- Produces: `PublicCase`, `ChallengeAnswer`, `load_public_cases()`, `render_messages()`, and `validate_answer()`.
- Consumes: versioned public cases and evidence packs.

- [ ] **Step 1: Write failing public dataset tests**

  Assert 50 unique IDs, ten domains with five cases each, 10/30/10 difficulty balance, two context files per case, valid evidence IDs, and an average rendered context between 4,100 and 4,700 estimated tokens.

- [ ] **Step 2: Run the tests and verify the missing package failure**

  Run: `uv run pytest tests/test_public_dataset.py -q`

  Expected: import or file-not-found failure for the unimplemented package.

- [ ] **Step 3: Implement the minimal typed public contracts**

  Use frozen dataclasses internally and Pydantic at JSON/CLI boundaries. Reject invalid paths, unknown citations, duplicate citations, non-boolean escalation, answers over 100 words, missing fields, and extra fields.

- [ ] **Step 4: Copy and revise the ten evidence packs and fifty public cases**

  Preserve the domain balance while applying the QA rubric: one controlling fact per easy case, two interacting facts per standard case, and at most three interacting facts plus one explicit distractor per hard case.

- [ ] **Step 5: Run dataset tests, formatting, and strict typing**

  Run: `uv run pytest tests/test_public_dataset.py -q && uv run ruff format --check . && uv run pyright`

  Expected: all commands exit zero.

### Task 2: Encrypted Prompt Submission

**Files:**
- Create: `submission/prompt.example.txt`
- Create: `submission/manifest.example.json`
- Create: `submission/encrypt_prompt.sh`
- Create: `src/hkpug_challenge/submission.py`
- Create: `scripts/verify_submission.py`
- Create: `tests/test_submission.py`
- Create: `.github/tournament/team_allowlist.json`
- Create: `.github/tournament/public_keys/tournament_ca_cert.pem`
- Create: `.github/tournament/public_keys/scorer_cert.pem`

**Interfaces:**
- Produces: a DER CMS prompt, canonical signed manifest, and public-key verification result.
- Consumes: local plaintext prompt, scorer certificate, team private key, team allowlist, and tournament CA.

- [ ] **Step 1: Write failing end-to-end crypto tests**

  Generate ephemeral certificates in a temporary directory and prove that a valid prompt verifies while tampered ciphertext, manifest, signature, team ID, or path fails.

- [ ] **Step 2: Run the crypto test and confirm failure**

  Run: `uv run pytest tests/test_submission.py -q`

- [ ] **Step 3: Implement canonical manifest validation and encryption script**

  Manifest fields are exactly `schema_version`, `team_id`, `prompt_path`, `prompt_sha256`, and `created_at`. `prompt_path` must equal `submission/prompt.txt.cms`; the prompt is plain UTF-8 text capped at 32 KiB after trusted decryption.

- [ ] **Step 4: Re-run crypto tests**

  Run: `uv run pytest tests/test_submission.py -q`

  Expected: all valid and tamper tests pass.

### Task 3: Hidden Suites And Fairness Validation

**Files:**
- Create: `src/hkpug_challenge/hidden.py`
- Create: `scripts/build_hidden_bank.py`
- Create: `scripts/encrypt_hidden_bank.sh`
- Create: `.github/tournament/hidden_bank.json.cms`
- Create locally only: `.local/hidden/domains/*.json`
- Create: `tests/test_hidden_bank.py`
- Create: `docs/qa/question-review.md`

**Interfaces:**
- Produces: eight frozen suites, each with one unused variant from every public family and a private reference rubric.
- Consumes: ten domain files containing eight variants per family.

- [ ] **Step 1: Write failing hidden-bank invariants**

  Validate 400 unique variants, 50 per suite, eight per family, no repeated question text, valid context/evidence IDs, expected escalation, reference answer under 100 words, required/forbidden citation disjointness, and identical difficulty/domain distribution in all suites.

- [ ] **Step 2: Run tests and verify missing hidden data failure**

  Run: `uv run pytest tests/test_hidden_bank.py -q`

- [ ] **Step 3: Author structured hidden variants by domain**

  Use controlled fact substitutions, boundary flips, missing-information escalation, stale authority, transaction state, incident state, untrusted instructions, and presentation changes. Do not generate scored variants at runtime.

- [ ] **Step 4: Conduct two independent human-style reviews**

  Record case IDs, severity, disposition, and reviewer in `docs/qa/question-review.md`; fix every Critical or Important ambiguity before encryption.

- [ ] **Step 5: Build and encrypt the frozen bank**

  Run: `uv run python scripts/build_hidden_bank.py --input .local/hidden/domains --output .local/hidden/hidden_bank.json && scripts/encrypt_hidden_bank.sh`

  Expected: only `.github/tournament/hidden_bank.json.cms` is tracked.

### Task 4: Fireworks Scoring And Portable Trace Bundle

**Files:**
- Create: `src/hkpug_challenge/fireworks.py`
- Create: `src/hkpug_challenge/scoring.py`
- Create: `src/hkpug_challenge/traces.py`
- Create: `scripts/score_submission.py`
- Create: `tests/test_scoring.py`
- Create: `tests/test_trace_bundle.py`

**Interfaces:**
- Produces: answer calls, one structured judge call per answer, criterion scores, aggregate score, and Opik-compatible trace/span/feedback payloads.
- Consumes: a decrypted prompt, one hidden suite, injected completion clients, immutable run metadata, and the previous leaderboard.

- [ ] **Step 1: Write failing scoring tests with deterministic fake clients**

  Prove schema/citation/escalation gates, weighted criteria, invalid-output handling, one answer and one bundled judge call per case, no prompt/reference leakage, stable IDs, and score range 0-100.

- [ ] **Step 2: Run tests and confirm the expected failures**

  Run: `uv run pytest tests/test_scoring.py tests/test_trace_bundle.py -q`

- [ ] **Step 3: Implement the Fireworks client and score contract**

  Answer calls use temperature 0 and a 256-token cap. Judge calls receive question, context, participant answer, reference answer, and rubric but never the participant prompt; they return bounded `answer_relevance`, `instruction_following`, and `faithfulness` values plus short reasons.

- [ ] **Step 4: Build portable Opik payloads**

  Bundle `trace_payload.json`, `span_payload.json`, `trace_feedback.json`, `span_feedback.json`, `run.json`, and `README.txt` in one deterministic archive. Exclude hidden references and expected answers.

- [ ] **Step 5: Run scoring and bundle tests**

  Run: `uv run pytest tests/test_scoring.py tests/test_trace_bundle.py -q`

### Task 5: Local Opik Replay

**Files:**
- Create: `src/hkpug_challenge/opik_replay.py`
- Create: `scripts/decrypt_feedback.sh`
- Create: `scripts/import_opik.py`
- Create: `tests/test_opik_replay.py`
- Create: `docs/import-opik.md`

**Interfaces:**
- Produces: replay of traces, spans, and feedback through Opik REST endpoints with idempotent IDs.
- Consumes: decrypted bundle directory, local Opik base URL, workspace, and optional bearer/basic authentication.

- [ ] **Step 1: Write a failing HTTP-level replay test**

  Use a local recording server and assert request ordering: traces batch, spans batch, trace feedback, span feedback. Verify retries are bounded and non-2xx responses fail visibly.

- [ ] **Step 2: Implement the smallest replay client and CLI**

  Default base URL is `http://localhost:5173/api`; project names are team/run specific; importing the same bundle twice must update or deduplicate rather than create conflicting IDs.

- [ ] **Step 3: Run replay tests and one local simulation**

  Run: `uv run pytest tests/test_opik_replay.py -q && uv run python scripts/import_opik.py --bundle tests/fixtures/trace-bundle --base-url http://127.0.0.1:<recording-port>`

### Task 6: Leaderboard And Live Dashboard

**Files:**
- Create: `src/hkpug_challenge/leaderboard.py`
- Create: `dashboard/index.html`
- Create: `dashboard/styles.css`
- Create: `dashboard/app.js`
- Create: `dashboard/leaderboard.json`
- Create: `tests/test_leaderboard.py`
- Create: `tests/test_dashboard.py`

**Interfaces:**
- Produces: append-only submissions, best/latest entries, criterion histories, and a responsive static dashboard.
- Consumes: score results and public leaderboard JSON.

- [ ] **Step 1: Write failing leaderboard and dashboard contract tests**

  Prove eight-attempt enforcement, duplicate-run idempotency, best-score selection, no secret fields, stable JSON schema, accessible headings/table, empty state, and all required assets.

- [ ] **Step 2: Implement leaderboard state transitions**

  Enforce attempt limits before model calls. Preserve all run summaries and compute best score with earliest-achievement tie breaking.

- [ ] **Step 3: Implement the dashboard**

  Show the challenge status, ranked best scores, latest movement, attempts used, three evaluation criteria, deterministic score, and per-team run trend. Do not expose prompts or hidden inputs.

- [ ] **Step 4: Verify desktop and mobile rendering**

  Run dashboard tests and capture Playwright screenshots at 1440x900 and 390x844 with no overflow or overlapping text.

### Task 7: GitHub Actions And Environment Bootstrap

**Files:**
- Create: `.github/workflows/validate-submission.yml`
- Create: `.github/workflows/trusted-score.yml`
- Create: `.github/workflows/deploy-pages.yml`
- Create: `scripts/admin/create_tournament_keys.sh`
- Create: `scripts/admin/create_team.sh`
- Create: `scripts/admin/configure_github.sh`
- Create: `tests/test_workflows.py`

**Interfaces:**
- Produces: untrusted validation artifact, trusted score, encrypted team feedback artifact, PR comment, leaderboard commit, and Pages deployment.
- Consumes: `FIREWORKS_API_KEY`, `SCORER_PRIVATE_KEY_PEM`, GitHub variables, signed submission, encrypted hidden bank, and team certificates.

- [ ] **Step 1: Write failing workflow static tests**

  Assert event separation, least-privilege permissions, pinned actions, allowed paths, no PR checkout in the trusted job, eight-attempt variable, secret names, concurrency, artifact retention, and Pages deployment.

- [ ] **Step 2: Implement and lint workflows**

  Run: `uv run pytest tests/test_workflows.py -q`

- [ ] **Step 3: Configure GitHub secrets and variables**

  Set `FIREWORKS_API_KEY` and `SCORER_PRIVATE_KEY_PEM` as Actions secrets. Set `MAX_ATTEMPTS=8`, `FIREWORKS_MODEL=accounts/fireworks/models/deepseek-v4-flash`, `LEADERBOARD_BRANCH=leaderboard`, and tournament timestamps as repository variables.

- [ ] **Step 4: Create leaderboard branch and enable GitHub Pages**

  Push a clean initial leaderboard branch, configure Actions as the Pages build source, and verify the deployment URL responds successfully.

### Task 8: Repeated Participant QA And Production Verification

**Files:**
- Create: `docs/qa/participant-simulations.md`
- Create: `docs/qa/production-checklist.md`
- Create: `.superpowers/sdd/progress.md`

**Interfaces:**
- Produces: durable QA findings, fixes, rerun evidence, and production sign-off.
- Consumes: the complete participant workflow and deployed GitHub repository.

- [ ] **Step 1: Run at least three independent participant simulations**

  Simulate key generation handoff, prompt editing, encryption, fork/PR submission, score feedback, artifact download, decryption, local Opik replay, prompt improvement, and resubmission. Reviewers must report confusing steps, not just software failures.

- [ ] **Step 2: Fix and re-run every Critical or Important finding**

  Record the first failure, requested correction, resulting commit, and successful rerun in `docs/qa/participant-simulations.md`.

- [ ] **Step 3: Run full local verification**

  Run: `uv sync --locked && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run pyright && git diff --check`

- [ ] **Step 4: Run live GitHub smoke submission**

  Submit the organizer test prompt, verify one attempt is charged exactly once, confirm a score comment and encrypted trace artifact, decrypt it, replay into local Opik, and verify the live dashboard updates.

- [ ] **Step 5: Complete the production checklist**

  Confirm all secrets exist without revealing values, hidden plaintext is absent from Git history and artifacts, Pages is live, Actions are green, question review is complete, and human instructions match the tested workflow.
