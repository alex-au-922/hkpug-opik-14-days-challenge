# Discovery QA Review

Date: 2026-07-12

This ledger records findings from independent discovery reviews before production implementation. `Open` findings block hidden-bank encryption. A finding becomes `Closed` only after a second reviewer confirms the revised case or workflow.

## Public Question Findings

| Severity | Case | Finding | Status |
| --- | --- | --- | --- |
| Important | REF-02 | The question does not distinguish one legitimate purchase plus one settled duplicate from two valid subscriptions. | Open |
| Important | SUB-04 | The outcome depends on whether the confirmed incident prevented cancellation reversal, but the question omits that deciding fact. | Open |
| Important | INT-01 | "Issue sync" does not say whether the integration is read-only or two-way, so the minimum OAuth permissions are ambiguous. | Open |
| Important | INT-04 | The conflict rule depends on the edited field and timing window, but neither is specified precisely. | Open |
| Moderate | REF-05 | The two card entries are not classified precisely enough for one deterministic remedy. | Open |
| Moderate | ACC-04 | The destination owner and verified corporate-domain evidence should be explicit. | Open |
| Moderate | SEC-03 | The case combines product security, incident response, and privacy routing; narrow the primary decision. | Open |
| Moderate | Hard tier | Ten hard cases overuse stale or untrusted instructions, limiting skill diversity and prompt-improvement headroom. | Open |

## Content Rules

1. Every case has one primary decision.
2. Every outcome-changing fact appears explicitly in the question or supplied evidence.
3. A precedence case includes its distractor and the governing fact.
4. Escalation is driven by a named missing fact or policy conflict.
5. A hard case combines at most three facts and two distinct reasoning skills.
6. Two reasonable compliant answers are a defect, not acceptable judge discretion.
7. The challenge uses roughly 4,400 context tokens per case. The earlier 800-token description is obsolete and must not appear in participant material.

## Workflow Findings

| Severity | Area | Finding | Required disposition | Status |
| --- | --- | --- | --- | --- |
| Critical | Trust boundary | Participant-controlled code must never run in a secret-bearing job. | Accept encrypted prompt text only; trusted scoring imports code only from `main`. | Open |
| Important | Attempts | The sibling repository counts daily attempts rather than eight total attempts. | Enforce eight total attempts before model calls. | Open |
| Important | Idempotency | A workflow rerun could consume another attempt without a stable submission identity. | Deduplicate by signed prompt digest and PR head SHA. | Open |
| Important | Leakage | Plain prompts, hidden cases, reference answers, or traces could leak through logs or artifacts. | Log only IDs and aggregates; encrypt team feedback before upload. | Open |
| Moderate | Validation drift | Allowed submission paths are duplicated in the sibling workflows. | Define one verifier contract and test both workflows against it. | Open |
| Critical | Trusted input | A trusted `workflow_run` must not trust an artifact produced by an untrusted workflow. | Re-fetch the three allowed PR blobs from the API at the event's immutable head SHA and repeat verification. | Open |
| Critical | Atomic attempts | Concurrent submissions can pass a non-atomic pre-check. | Serialize reservation updates globally; resume by submission identity after partial failure. | Open |
| Important | Reproducibility | Temperature zero does not make a future external model call bit-for-bit reproducible. | Persist raw request/response and version metadata; replay recorded scoring without calling the model again. | Open |
| Important | Cost controls | A 50-case run needs explicit call and token ceilings. | Cap prompt size, calls, estimated input tokens, output tokens, retries, and add a kill switch. | Open |

## Opik Import Decision

Database snapshots are rejected for participant feedback. A snapshot would require version-matched restoration across MySQL, ClickHouse, MinIO, Redis, and ZooKeeper and is not a portable challenge artifact.

The production flow uses a versioned JSON bundle and documented Opik REST replay in this order:

1. `POST /api/v1/private/traces/batch`
2. `POST /api/v1/private/spans/batch`
3. `PUT /api/v1/private/traces/feedback-scores`
4. `PUT /api/v1/private/spans/feedback-scores`

Each team receives only its consumed hidden cases, model outputs, spans, and score reasons. Reference answers, private rubrics, and unused variants are excluded.

This intentionally reveals consumed cases to the submitting team because diagnosis in Opik is the educational objective. The tournament accepts the residual risk that teams could share decrypted feedback. Mitigations are one-time variants per team, encrypted delivery, no expected answers, deterministic team/attempt assignment, an explicit no-sharing rule, and baseline normalization. Redacting case inputs would defeat the approved improvement workflow and is therefore rejected.
