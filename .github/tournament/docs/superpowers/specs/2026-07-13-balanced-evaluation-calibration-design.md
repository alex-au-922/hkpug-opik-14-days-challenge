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

## Discriminative Case Contract

Each case records its archetype explicitly. The five case slots in every domain are:

1. `direct_policy_lookup` (easy): at least one citation group, two required conclusions, and two prohibited claims.
2. `multi_source_synthesis` (standard): at least two citation groups, three required conclusions drawn across applicable sources, and three prohibited claims.
3. `conflicting_or_stale_evidence` (standard): at least two citation groups, three required conclusions, three prohibited claims, at least one named non-authoritative source, and a version or authority decision.
4. `prompt_injection_or_untrusted_evidence` (hard): at least two citation groups, four required conclusions, four prohibited claims, and at least one named non-authoritative source carrying the unsafe or injected instruction.
5. `ambiguous_authority_or_escalation` (hard): at least two citation groups, four required conclusions, and four prohibited claims, including the missing or conflicting fact, the safe current action, and the correct escalation state.

The fixed system wrapper must not supply source-precedence, injection-resistance, citation-selection, or escalation strategy. Those behaviors belong in the participant prompt. Context documents remain unchanged; case difficulty comes from evidence selection and decision structure rather than additional prose.

Questions contain at most 80 words. Reference answers retain the existing 100-word limit. Required and prohibited rubric statements remain concise so stricter cases do not materially increase judge input size.

## Token Budget

- One complete attempt always evaluates all 50 cases with 100 model calls.
- Candidate and judge prompt and completion usage together must remain at or below 500,000 tokens.
- The current production calibration measured 319,359 tokens for 40 discovery cases, projecting approximately 399,000 for all 50.
- Public context files are frozen for this revision. The rebuilt bank must retain at least 15% measured headroom below the hard limit.
- Scoring reports aggregate total token usage and fails closed if reported usage exceeds 500,000.

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
