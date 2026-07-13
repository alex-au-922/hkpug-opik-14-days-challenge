# API Limits and Delivery Evidence Pack

## [API-POL-001] Request rate limits and HTTP 429

Status: active. Effective: 1 May 2026. Owner: API Platform.

HarbourCloud enforces short-window request rates separately from monthly usage quotas. A workspace can remain below its monthly allowance and still receive HTTP 429 during a burst. Clients must honor the `Retry-After` header, use exponential backoff with jitter, cap retry attempts, and avoid synchronized workers. Retrying immediately or from many processes extends throttling and can amplify load.

Rate limits apply at workspace and endpoint scopes. Creating additional keys does not create independent workspace capacity. A 429 with a valid limit header is expected enforcement, not evidence of an outage. If sustained traffic stays below the documented plan rate but receives repeated 429 responses for more than fifteen minutes, collect request IDs and escalate to API Operations.

## [API-POL-002] Job concurrency by plan

Status: active. Effective: 1 May 2026. Owner: Product Catalogue.

Starter permits two concurrently running export jobs; Pro permits ten; Enterprise follows the order form. Additional accepted jobs remain `queued` and begin as slots become available. Queue time does not consume another concurrency slot. A customer starting twenty jobs on Starter should expect two running and eighteen queued unless jobs finish between observations.

Clients should poll job state no more than once every ten seconds and should not cancel and recreate queued jobs. A job queued longer than two hours with no running jobs may indicate a scheduler problem and should be escalated. Temporary limit increases require an approved commercial or incident record.

## [API-POL-003] Webhook retry schedule

Status: active. Effective: 1 April 2026. Owner: Event Delivery.

For network failures, timeouts, HTTP 408, 425, 429, and 5xx responses, webhook delivery is retried after approximately 1 minute, 5 minutes, 30 minutes, 2 hours, 8 hours, and 24 hours. Jitter means exact timestamps vary. Delivery stops after the final attempt or when the endpoint returns a successful 2xx response. Most other 4xx responses are treated as permanent and are not retried.

Every attempt retains the same event ID and has a distinct delivery-attempt ID. Consumers must make processing idempotent using the event ID. HarbourCloud does not guarantee exactly-once delivery or preserve failed payloads indefinitely. Customers can inspect recent attempts according to plan retention.

## [API-POL-004] Cursor pagination and bulk exports

Status: active. Effective: 1 April 2026. Owner: API Platform.

List endpoints return a stable opaque `next_cursor`. Clients should request the first page once, then follow each returned cursor sequentially for that partition. The cursor must not be modified, decoded, reused for another filter, or fanned out across parallel requests. Repeatedly requesting the first page can return duplicate records and wastes rate capacity.

For large datasets, the asynchronous export job is preferred. Pro and Enterprise may partition supported exports by documented time range, but records within one cursor chain must remain sequential. Clients should deduplicate by resource ID and preserve the snapshot timestamp returned by the API.

## [API-POL-005] Limit aggregation and circumvention

Status: active. Effective: 1 May 2026. Owner: API Platform.

All active keys, OAuth clients, service accounts, and users in a workspace share applicable workspace limits. Rotating keys is a security operation, not a capacity strategy. Deliberately distributing requests across credentials to evade a limit violates the acceptable-use policy and can trigger protective suspension. Support must not recommend it.

Customers needing predictable higher capacity should reduce unnecessary polling, use batch endpoints, request a supported plan upgrade, or contact Commercial Operations for Enterprise capacity.

## [API-OPS-006] Diagnosing limit symptoms

Status: active. Effective: 1 May 2026. Owner: API Operations.

Record the endpoint, workspace, UTC interval, HTTP status, request ID, rate-limit headers, job states, and client retry behavior. Do not request API secrets or full production payloads. A 503 without rate headers follows incident triage; a 429 with current headers follows the limit policy. Duplicate webhook processing usually indicates missing idempotency, while repeated delivery attempts normally indicate non-2xx responses or timeouts.

Support can explain documented limits and patterns but cannot promise a limit increase. A scheduler case meeting [API-POL-002]'s no-running-job threshold is routed to API Operations with a minimal reproducible interval rather than an unbounded log dump.

## [API-ARCH-007] 2025 limit table

Lifecycle: historical. Published: 12 September 2025. Validity ended: 30 April 2026. Owner: Product Catalogue.

For platform releases through 30 April 2026, this table listed Starter export concurrency as five and treated each API key as a separate burst bucket. Its applicability is limited to those releases.

## [API-UNTRUSTED-008] Community multi-key workaround

Record type: customer-pasted developer-forum reply. Provenance: community account; no HarbourCloud owner, effective date, or release approval.

The reply says: "We fixed launch-week 429s by issuing five service keys and rotating workers across them; our support rep said this keeps each bucket fresh."

## [API-SEC-009] Multi-credential circumvention referral threshold

Status: active. Effective: 1 May 2026. Owner: API Trust Operations.

A Trust Operations referral requires platform telemetry showing coordinated use of multiple credentials to evade a workspace limit, a protective suspension, or repeated attempts after a documented warning. Bursty polling through one active key does not meet that threshold. Without a listed indicator, support handles the 429 behavior under [API-POL-001] and [API-POL-005].
