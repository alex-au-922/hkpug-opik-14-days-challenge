# Mini Workshop Debug Report

You are the engineer asked to summarize a debugging session for your manager.
A BA has flagged six suspicious support-agent runs before release.

Use both panes:

- Opik shows what happened in the run.
- The project Dashboard gives the project-level trace overview.
- Experiments show prompt-release evidence for Case 006.
- Code shows the intended logic for a few review points.

Most answers are in one Opik span. Code-required questions are clearly marked
and require a short look at the Python code.

Open one GitHub issue for your group, then submit answers as comments in that
issue. Each comment is graded once.

Answers must be deterministic and short. Use exact span names, document IDs,
metric names, or the choice tokens shown below. Do not write prose explanations
in answer fields.

```text
Case: 001
A: <short-answer-token>
B: <span-name>
C: <document-id>
D: <choice-token>
```

## 001 - Policy Evidence Does Not Match Customer

BA flag: The support answer says an activated Starter customer can receive a
30-day refund. BA suspects the answer used the wrong policy.

A. Which short token best describes what the agent answered?
Choose one: `eligible-30-day-refund`, `service-credit-only`,
`not-refundable`.

B. Which Opik span shows the policy documents retrieved for the answer?

C. Which retrieved document should not have been used for an HK Starter
customer?

D. `[Code]` In `shared/fixtures.py`, which token describes the correct HK
Starter policy for activated seats?
Choose one: `activated-refundable`, `activated-not-refundable`,
`pro-policy-applies`.

## 002 - Slow Run With Broad Retrieval Fallback

BA flag: This refund run was much slower than nearby runs. BA wants to know
whether the answer is safe or whether the fallback path changed the evidence.

A. Ignoring the root orchestration span, which retrieval span took the longest?

B. Which fallback retrieval span ran after the primary retrieval problem?

C. Did the fallback use stronger or weaker evidence than the primary intended
filter? Choose one: `stronger-evidence`, `weaker-evidence`.

D. Should the manager approve this run without review?
Choose one: `approve`, `manual-review`, `reject`.

## 003 - Tool Result Is Confident But Input Is Wrong

BA flag: The refund calculator returned a confident "eligible" result, but the
customer complained that they are on Starter, not Pro.

A. Which span first shows the parsed request product as `starter` before the
tool call?
Choose one: `003.parse_refund_request`, `003.map_tool_arguments`,
`003.compose_tool_answer`.

B. Which calculator span receives `product: pro` in its input?

C. `[Code]` In `cases/case_003_tool_argument.py`, what short token names the
hard-coded argument or mapping causing the tool to receive `product="pro"`?
Choose one: `product=pro`, `product=starter`, `region=hk`.

D. What should the manager conclude: tool failure, mapping failure, or model
failure? Choose one: `tool-failure`, `mapping-failure`, `model-failure`.

## 004 - Streamed Draft Was Persisted After Cutoff

BA flag: The ticket summary looks incomplete. BA wants to know whether this was
a model quality issue or an application persistence issue.

A. Which span shows the streamed model output and finish reason?

B. What finish reason did the model return?

C. Which span persisted the answer despite the incomplete stream?

D. `[Code]` In `cases/case_004_stream_cutoff.py`, which missing check should
block saving? Choose one: `finish-reason-check`, `ticket-id-check`,
`region-check`.

## 005 - Issue Summary Contains Unsafe Comment Text

BA flag: The GitHub issue summary includes an internal debug token and tells
support to bypass approval.

A. Which retrieved item contains the unsafe instruction?

B. Which span shows that untrusted text was included in the prompt without a
boundary?

C. Which span shows the guardrail result?

D. What should the manager decide for this summary?
Choose one: `approve`, `block-or-rewrite`, `manual-review-only`.

## 006 - Release Candidate Looks Good But Gate Is Too Weak

BA flag: The app selected a prompt version for release, but BA believes another
candidate is safer.

A. In Logs, which prompt version did the app select?

B. In Experiments, which prompt version should ship based on faithfulness and
release-gate scores?

C. Which metric made the selected candidate look attractive?

D. `[Code]` In `cases/case_006_release_gate.py`, what short token names the
missing release selection condition?
Choose one: `faithfulness-expert-gate`, `cost-only-gate`,
`answer-relevance-gate`.
