# Balanced Evaluation Calibration

## Objective

Create a competitive 50-case prompt-engineering tournament where discovery and holdout use different cases with the same domain, difficulty, and failure-mode distributions. Calibrate the bank with four cumulative prompt strategies and report each exact prompt with its score.

## Evaluation Matrix

- Ten support domains, five cases per domain.
- Forty discovery cases and ten holdout cases.
- Difficulty distribution:
  - Discovery: 8 easy, 16 standard, 16 hard.
  - Holdout: 2 easy, 4 standard, 4 hard.
- Five case archetypes appear in both partitions at an 8:2 ratio:
  - direct policy lookup
  - multi-source synthesis
  - conflicting or stale evidence
  - prompt injection or untrusted evidence
  - ambiguous authority or escalation
- Each domain contains one case from every archetype. The holdout slot rotates across domains so participants cannot infer a special hidden-case pattern.

## Calibration Attempts

Raise the daily cap from two to four while retaining the eight-attempt tournament cap. Run four cumulative participant prompts:

1. Output-contract baseline.
2. Add evidence authority and citation selection.
3. Add conflict, stale evidence, and injection resistance.
4. Add uncertainty and escalation decision rules.

Each later prompt retains the earlier instructions. Good general improvements should usually improve the score, but the system does not force monotonicity; holdout regressions remain valid evidence of overfitting.

## Competitive Targets

- Weak: 35-50.
- Starter: 50-65.
- Good: 70-82.
- Excellent: 85-95.

Calibration succeeds when the strategies produce useful separation, discovery and holdout remain directionally consistent, and no strategy receives an artificially monotonic score.

## Security And Reporting

- All 50 cases run on every attempt.
- Discovery feedback contains detailed traces; holdout feedback remains aggregate-only.
- The encrypted evaluation bank stays on the organizer branch.
- The report exposes calibration prompts and aggregate scores, never hidden cases, references, or holdout details.
