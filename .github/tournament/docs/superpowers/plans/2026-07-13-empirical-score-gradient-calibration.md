# Empirical Score Gradient Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recalibrate all 50 private tournament cases with real DeepSeek V4 Flash outputs so cumulative prompt rules produce a measurable score gradient while every run remains below 1,000,000 tokens.

**Architecture:** Add a private calibration runner that executes a fixed four-profile prompt ladder through the production `score_prompt()` path and summarizes results by partition, archetype, criterion, and case. Tighten the Qwen judge contract so required conclusions and prohibited claims produce auditable semantic caps, remove participant-strategy instructions from the common handbook, then use each real calibration report to rewrite the failing private cases and repeat until all score-gradient gates pass.

**Tech Stack:** Python 3.10+, Pydantic 2, pytest, uv, Ruff, Pyright, Fireworks DeepSeek V4 Flash candidate, Fireworks Qwen3.7 Plus judge, encrypted CMS evaluation bank.

## Global Constraints

- Every calibration profile evaluates all 50 cases: 40 discovery and 10 holdout.
- Candidate model is exactly `accounts/fireworks/models/deepseek-v4-flash`.
- Judge model is exactly `accounts/fireworks/models/qwen3p7-plus`.
- Candidate plus judge prompt and completion usage must not exceed 1,000,000 tokens per profile; the calibration target is at most 850,000 tokens.
- Domain policy evidence remains factually stable. The common handbook may be rewritten once to remove authority, citation, injection, escalation, and output-contract instructions that duplicate the participant prompt; after that rewrite, public contexts are frozen for every calibration round.
- Private case questions, references, rubrics, outputs, and reports remain untracked and must never be exposed in participant-facing branches or artifacts.
- Discovery and holdout retain the exact 8:2 archetype ratio and the same difficulty distribution.
- The four participant profiles are cumulative: output contract; evidence authority; conflict/stale/injection resistance; uncertainty and escalation.
- Calibration passes only when the final profile beats the output-contract baseline by at least 10 overall points, evidence authority improves the targeted evidence/faithfulness contribution by at least 2 points, conflict resistance improves the conflicting/untrusted archetype average by at least 4 points, escalation rules improve the ambiguous/escalation archetype average by at least 4 points, final escalation contribution for that archetype is at least 9/10, the final discovery/holdout gap is at most 10 points, and no profile exceeds the token limits.
- Questions must not name their archetype or explicitly tell the model which authority, trust-boundary, or escalation strategy to apply. Escalation labels must not be predictable from case position or archetype.

---

### Task 1: Auditable semantic judge caps

**Files:**
- Modify: `.github/tournament/src/hkpug_challenge/fireworks.py`
- Modify: `.github/tournament/src/hkpug_challenge/scoring.py`
- Modify: `.github/tournament/tests/test_scoring.py`

**Interfaces:**
- Consumes: `EvaluationCase.rubric.required_points`, `prohibited_claims`, and `non_authoritative_evidence`.
- Produces: judge JSON containing zero-based `required_points_met`, `prohibited_claims_present`, and `non_authoritative_evidence_used`; `_score_case()` applies deterministic tier caps before criterion weights; `score_prompt(include_holdout_details=False)` exposes holdout case rows only when the private calibration runner explicitly opts in.

- [ ] Write failing tests proving a judge cannot award 100 relevance when a material required point is missing and cannot award 100 faithfulness when a prohibited claim or non-authoritative source is used as authority.
- [ ] Run `uv run pytest tests/test_scoring.py -q` and verify the new tests fail because semantic audit fields and caps do not exist.
- [ ] Add a scoring-specific `SCORING_JUDGE_RESPONSE_FORMAT` and extend `_JudgePayload` with validated semantic audit fields; retain the legacy playground response schema, and reject indexes outside each case rubric and evidence IDs outside `non_authoritative_evidence`.
- [ ] Cap `answer_relevance` by required-point coverage tiers and cap `faithfulness` at 50 when a prohibited claim or non-authoritative authority is present.
- [ ] Add a default-off `include_holdout_details` switch and prove participant scoring still hides holdout rows while private calibration receives all ten.
- [ ] Run `uv run pytest tests/test_scoring.py -q`, `uv run ruff format --check src tests`, and `uv run pyright`; expect all checks to pass.

### Task 2: Private four-profile calibration runner

**Files:**
- Create: `.github/tournament/src/hkpug_challenge/calibration.py`
- Create: `.github/tournament/scripts/run_calibration.py`
- Create: `.github/tournament/tests/test_calibration.py`
- Create locally and keep ignored: `.local/calibration/prompts/*.txt`

**Interfaces:**
- Consumes: `score_prompt(include_holdout_details=True)`, an already-decrypted private `EvaluationBank`, a directory containing exactly four cumulative prompt files, and Fireworks clients.
- Produces: mode-0600 private JSON containing each profile prompt hash, aggregate score, partition aggregates, per-archetype criteria, per-case deltas, token usage, and named gate results.

- [ ] Write failing public-interface tests for profile ordering, cumulative-rule validation, archetype aggregation, score deltas, token gates, and mode-0600 output.
- [ ] Run `uv run pytest tests/test_calibration.py -q` and verify failure because the runner does not exist.
- [ ] Implement immutable calibration profile/result models and one `run_calibration()` entry point that calls production `score_prompt()` once per profile.
- [ ] Implement the CLI with explicit paths, fail-fast environment/model validation, progress logging, and no prompt text in reports.
- [ ] Add the exact four cumulative private prompts and ensure each later prompt contains every previous rule plus one strategy block.
- [ ] Run calibration tests, Ruff formatting/check, and strict Pyright; expect all checks to pass.

### Task 3: First real-model diagnostic pass

**Files:**
- Read: `.local/evaluation/evaluation_bank.json`
- Create locally and keep ignored: `.local/calibration/round-01.json`
- Create locally and keep ignored: `.local/calibration/round-01-review.md`

**Interfaces:**
- Consumes: authenticated Fireworks access and the four-profile runner.
- Produces: a complete 400-call report covering four profiles x 50 candidate calls x candidate/judge, plus a human-readable failing-case queue.

- [ ] Confirm Fireworks credits and record only the numeric available credit in the private review, never the API key.
- [ ] Run all four profiles against all 50 cases and save actual token usage.
- [ ] Reject the round immediately if any profile exceeds 1,000,000 tokens; flag profiles above 850,000 for prompt/rubric compaction.
- [ ] Rank failing cases by missed profile delta, generic near-perfect judge scores, discovery/holdout divergence, and unstable escalation.
- [ ] Assign every failing case to exactly one domain rewrite batch without exposing holdout contents outside the organizer workspace.

### Task 4: Evidence-driven 50-case rewrite

**Files:**
- Modify once, then freeze: `public/contexts/company_handbook.md`
- Modify locally and keep ignored: `.local/evaluation/domains/*.json`
- Regenerate locally and keep ignored: `.local/evaluation/evaluation_bank.json`
- Modify tracked encrypted artifact: `.github/tournament/evaluation_bank.json.cms`
- Modify tests only when the validated bank contract changes: `.github/tournament/tests/test_evaluation_bank.py`

**Interfaces:**
- Consumes: round report with actual candidate outputs and per-case deltas.
- Produces: 50 cases in which each intended rule changes an observable answer decision: source selection, citation coverage, conflict handling, injection rejection, or escalation.

- [ ] Split the ten domain files into disjoint rewrite batches and give each worker the relevant private report rows and profile outputs.
- [ ] Replace the common handbook's participant-strategy instructions with neutral shared facts and routing vocabulary; remove its strategy IDs from private references and rubrics.
- [ ] For each case, preserve domain/archetype/partition while making the missing rule necessary to reach the reference answer; do not add answer-key language to the question.
- [ ] Make every required point atomic and observable, every prohibited claim plausible under a weaker rule, and every non-authoritative evidence ID correspond to an actual tempting distractor in the unchanged contexts.
- [ ] Balance true/false escalation decisions within each archetype and remove cue phrases such as `safe action and escalation decision`, overt `archived/stale evidence` labels, and question narration that announces an injection.
- [ ] Rebuild the canonical bank and run all bank validators, semantic-duplicate checks, and public-context byte comparison.
- [ ] Encrypt the canonical bank and verify a CMS decrypt round trip is byte-for-byte identical.

### Task 5: Repeat until gradient gates pass

**Files:**
- Create locally and keep ignored: `.local/calibration/round-NN.json`
- Create locally and keep ignored: `.local/calibration/round-NN-review.md`
- Modify local domain files and tracked encrypted bank as required by each failed round.

**Interfaces:**
- Consumes: latest bank and the unchanged four-profile ladder.
- Produces: one final report in which every global constraint gate is `pass`.

- [ ] Run the full four-profile batch after each rewrite.
- [ ] If a gate fails, rewrite only the cases responsible for that gate and document the evidence from the actual outputs.
- [ ] Stop rewriting when all gates pass; do not tune holdout cases independently from their matching discovery archetype distribution.
- [ ] Record exact overall, discovery, holdout, archetype, criterion, and token deltas for the accepted round.

### Task 6: Production verification and publication

**Files:**
- Modify: `.github/tournament/docs/superpowers/specs/2026-07-13-balanced-evaluation-calibration-design.md`
- Modify: `.github/tournament/docs/superpowers/plans/2026-07-13-discriminative-evaluation-bank.md`
- Modify tracked encrypted bank and scorer files produced by Tasks 1-5.
- Synchronize changed participant-visible contexts to the participant `main` branch after the organizer commit is accepted.

**Interfaces:**
- Consumes: accepted private calibration report.
- Produces: tested organizer commit and immutable `ORGANIZER_REF`; participant branches receive no private data.

- [ ] Document the accepted aggregate score ladder and token usage without exposing prompts, cases, references, rubrics, or holdout details.
- [ ] Run `uv run pytest -q`, `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, and `uv run pyright`.
- [ ] Decrypt the tracked CMS bank and compare it byte-for-byte with the validated private canonical bank.
- [ ] Review the complete organizer diff for private-data leakage and verify participant-facing branches contain only the encrypted bank where required.
- [ ] Commit and push the organizer branch, then update `ORGANIZER_REF` to the exact tested commit.
