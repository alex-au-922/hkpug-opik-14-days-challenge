# Participant Main And Organizer Branch Design

## Goal

Keep the public default branch focused on participants while preserving a working
tournament pipeline in the same public repository.

## Branch Contract

`main` contains only:

- `.github/workflows/`
- `.gitignore`
- `README.md`
- `public/`
- `starter/`
- `submission/`

`organizer` contains the complete trusted implementation, tests, evaluation bank,
team registration data, public certificates, helper source, and dashboard source.
The branch is public by explicit organizer choice, so it is an organization boundary,
not a confidentiality boundary.

`leaderboard` remains the generated Pages/state branch. It supplies the dashboard
and encrypted attempt state to Pages and the scoring workflow.

## Trusted Workflow Ref

Fork pull-request workflows cannot read repository variables, so participant
validation hard-pins the reviewed organizer commit SHA directly in the trusted
base workflow. Repository variable `ORGANIZER_REF` stores the same reviewed SHA
for trusted scoring and playground workflows. Pull requests cannot choose either
ref. Workflow code must never execute scorer code from a participant head SHA.

Helper release workflows continue to check out exact `helper-vX.Y.Z` tags so release
builds remain reproducible.

## Evaluation And Feedback Contract

Every scored attempt evaluates all 50 cases: 40 discovery and 10 holdout. Each case
uses one answer call and one judge call, for 100 model calls per scored attempt.

The encrypted participant feedback bundle contains traces only for the 40 discovery
cases. Each discovery trace contains a `model.answer` span and an
`evaluation.judge` span. The ten holdout questions, contexts, outputs, case IDs, and
judge reasons never enter the trace bundle. Only aggregate holdout case count,
criterion totals, and score are returned.

## Opik Tutorial

The participant tutorial must explain:

- how to start local Opik;
- how to decrypt and load the feedback artifact;
- why a complete run imports 40 traces rather than 50;
- how to inspect `model.answer` and `evaluation.judge` spans;
- how to interpret the seven score columns; and
- that holdout feedback is aggregate-only.

## Verification

- Python tests, Ruff, and Pyright pass on `organizer`.
- Go tests and cross-platform helper builds pass on `organizer`.
- Workflow tests require an immutable organizer SHA checkout and verify that fork
  validation does not depend on repository variables.
- `git ls-tree origin/main` shows no `.github/tournament` paths.
- Validation, Pages, and helper release workflows remain registered on `main`.
- The live Opik tutorial contains the 50/40/10 explanation.
