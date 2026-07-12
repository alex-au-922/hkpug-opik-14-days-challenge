# Participant Main And Organizer Branch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a participant-only `main` branch while retaining the trusted tournament implementation on `organizer` and documenting the 40-trace Opik feedback workflow.

**Architecture:** The public repository uses `main` for participant material, `organizer` for trusted source and tests, and `leaderboard` for generated Pages/state. Fork validation hard-pins a reviewed organizer SHA because GitHub withholds repository variables from fork pull-request workflows; trusted scoring and playground workflows use the maintainer-controlled `ORGANIZER_REF` variable.

**Tech Stack:** Git branches, GitHub Actions, Python 3.10 with uv/pytest/Ruff/Pyright, Go, static HTML/CSS.

## Global Constraints

- Every scored attempt evaluates exactly 50 cases: 40 discovery and 10 holdout.
- Participant feedback contains exactly 40 discovery traces and no holdout trace details.
- Participant PR code is never executed with secrets or write permissions.
- `main` contains only `.github/workflows`, `.gitignore`, `README.md`, `public`, `starter`, and `submission`.
- Organizer source is public by explicit organizer choice and is not a confidentiality boundary.

---

### Task 1: Trusted Organizer Ref

**Files:**
- Modify: `.github/workflows/validate-submission.yml`
- Modify: `.github/workflows/trusted-score.yml`
- Modify: `.github/workflows/playground-smoke.yml`
- Test: `.github/tournament/tests/test_workflows.py`

**Interfaces:**
- Consumes: a hard-pinned 40-character organizer SHA for fork validation and repository variable `ORGANIZER_REF` for trusted events.
- Produces: trusted checkout at `trusted/` containing `.github/tournament` and `public`.

- [ ] Add failing workflow tests requiring immutable organizer SHAs and forbidding participant head refs.
- [ ] Run `uv run --frozen pytest tests/test_workflows.py -q` and confirm the new assertions fail.
- [ ] Hard-pin the organizer SHA in fork validation; use `${{ vars.ORGANIZER_REF }}` in trusted scoring and playground workflows; disable persisted credentials.
- [ ] Re-run the workflow tests and confirm they pass.
- [ ] Commit with `fix: load trusted code from organizer ref`.

### Task 2: Tournament-Specific Opik Tutorial

**Files:**
- Modify: `.github/tournament/dashboard/opik/index.html`
- Test: `.github/tournament/tests/test_dashboard.py`

**Interfaces:**
- Consumes: decrypted feedback bundle produced by `hkpug-opik-helper decrypt`.
- Produces: participant guidance matching the 50/40/10 trace contract.

- [ ] Add failing dashboard assertions for 50 evaluated cases, 40 imported discovery traces, two named spans, seven criteria, and aggregate-only ten holdouts.
- [ ] Run `uv run --frozen pytest tests/test_dashboard.py -q` and confirm the assertions fail.
- [ ] Add concise trace-count and trace-anatomy sections to the Opik tutorial.
- [ ] Re-run the dashboard test and confirm it passes.
- [ ] Commit with `docs: explain tournament traces in Opik tutorial`.

### Task 3: Publish Branch Split

**Files:**
- Delete from `main`: `.github/tournament/**`
- Preserve on `organizer`: `.github/tournament/**`, participant files, and workflows.
- Configure: GitHub repository variable `ORGANIZER_REF`.

**Interfaces:**
- Consumes: reviewed organizer commit SHA.
- Produces: clean participant `main` and executable trusted workflows.

- [ ] Push the tested implementation to `organizer`.
- [ ] Set `ORGANIZER_REF` to the pushed organizer commit SHA.
- [ ] Remove `.github/tournament` from the main worktree without changing participant files or workflows.
- [ ] Verify the main tree allowlist with `git ls-tree -r --name-only HEAD`.
- [ ] Commit with `chore: keep main participant facing` and push directly to `main`.

### Task 4: End-To-End Verification

**Files:**
- Verify only; no planned source changes.

**Interfaces:**
- Consumes: pushed `main`, `organizer`, `leaderboard`, and repository variables.
- Produces: launch evidence for branch contents, tests, workflows, Pages, and release assets.

- [ ] Run the complete Python suite, Ruff, Pyright, Go tests, and Go vet on `organizer`.
- [ ] Verify `origin/main` contains no `.github/tournament` paths.
- [ ] Dispatch Pages from `leaderboard` and verify the live Opik tutorial.
- [ ] Verify the existing helper release and its six platform assets remain available.
- [ ] Inspect Actions registration and report any workflow that cannot be exercised without a participant PR.
