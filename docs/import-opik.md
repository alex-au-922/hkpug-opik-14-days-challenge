# Import discovery feedback into Opik

The decrypted feedback bundle can be replayed into local or hosted Opik without a
database snapshot. The importer uses Opik's batch REST endpoints in dependency
order and does not install the Opik Python SDK.

## Compatibility target

The request contract follows the current official endpoints for
[trace batches](https://www.comet.com/docs/opik/latest/reference/rest-api/traces/create-traces),
[span batches](https://www.comet.com/docs/opik/reference/rest-api/spans/create-spans),
[trace feedback](https://www.comet.com/docs/opik/reference/rest-api/traces/score-batch-of-traces),
and [span feedback](https://www.comet.com/docs/opik/v1/reference/rest-api/spans/score-batch-of-spans).
The workshop deployment uses Opik Helm chart `2.1.14`; that is the pinned server
target for this importer. Opik documents that its low-level REST API is not
guaranteed to remain backward compatible, so rerun this recording test before a
server upgrade.

## Accepted bundle

Pass the directory created after decrypting one attempt. It must contain:

```text
run.json
trace_payload.json
span_payload.json
trace_feedback.json
span_feedback.json
```

The boundary is intentionally strict:

- `run.json.bundle_partition` must be `discovery`.
- `trace_payload.json`, `span_payload.json`, and both feedback files contain only
  their expected top-level collection.
- Every trace and span declares `metadata.partition: "discovery"`.
- Trace and span IDs are stable UUIDs. Span links and feedback IDs must resolve
  to entities in the same discovery bundle.
- `run.json.holdout` may contain only aggregate `case_count`, `criteria`, and
  `score` fields. Holdout case inputs, outputs, IDs, spans, and reasons are
  rejected before any network request.

The importer rewrites `project_name` consistently when `--project-name` is
provided, but never generates or changes entity IDs. Replaying the same bundle
sends structurally identical JSON payloads with the same IDs, so the importer
cannot create a second entity identity for the same bundle.

## Run locally

With Opik at its default local address:

```bash
uv run python scripts/import_opik.py \
  --bundle .local/feedback/attempt-03
```

The default base URL is `http://localhost:5173/api`. For another instance:

```bash
uv run python scripts/import_opik.py \
  --bundle .local/feedback/attempt-03 \
  --base-url https://opik.example/api \
  --workspace team-07 \
  --project-name hkpug-team-07-run-03
```

For bearer authentication, set `OPIK_API_KEY`. For HTTP Basic authentication,
set `OPIK_BASIC_AUTH_USERNAME` and `OPIK_BASIC_AUTH_PASSWORD`, or pass the
username with `--basic-username` while keeping the password in the environment.
Bearer and Basic authentication cannot be enabled together.

The client retries only `408`, `425`, `429`, `500`, `502`, `503`, and `504`, plus
transport timeouts/errors. The default is two retries with exponential delay;
`--max-retries` has a hard ceiling of five. Any final non-2xx response exits
nonzero and includes the endpoint, status, and the first 500 response bytes.

## Verified local simulation

Verified on 2026-07-12 with Python 3.10. The test starts a loopback recording
HTTP server, creates a complete 40-case discovery bundle, invokes the real CLI
as a subprocess, and inspects every request.

```bash
uv run pytest \
  tests/test_opik_replay.py::test_import_cli_completes_full_replay_and_prints_machine_readable_summary \
  -q
```

Observed result:

```text
1 passed in 0.67s
```

The CLI emitted:

```json
{
  "project_name": "hkpug-team-07-run-03",
  "request_count": 4,
  "span_count": 40,
  "span_feedback_count": 40,
  "trace_count": 40,
  "trace_feedback_count": 40
}
```

The server recorded exactly:

```text
POST /api/v1/private/traces/batch                 traces=40
POST /api/v1/private/spans/batch                  spans=40
PUT  /api/v1/private/traces/feedback-scores       scores=40
PUT  /api/v1/private/spans/feedback-scores        scores=40
```

The complete focused QA run was:

```bash
uv run pytest tests/test_opik_replay.py -q
```

```text
19 passed in 9.26s
```

This simulation proves validation, request order, stable request IDs,
authentication headers, retry bounds, and visible failure behavior. It does not
replace an acceptance run against a real Opik server after upgrading Opik.
