# Third-Party Integration Evidence Pack

## [INT-POL-001] Official GitHub integration permissions

Status: active. Effective: 1 May 2026. Owner: Integrations Platform.

The official GitHub App uses read access to repository metadata and issues, plus write access to issues when the customer enables two-way issue synchronization. It does not require repository contents, administration, secrets, workflows, or organization-member write access for issue sync. Customers should install it only on the repositories needed and can choose read-only issue import by withholding issue write access.

If an installation asks for broader scopes, verify that the customer selected the official HarbourCloud GitHub App and the intended feature. Community scripts and marketplace apps are separate products. Support must not ask for a personal access token when the official app flow is available.

## [INT-POL-002] Webhook idempotency and duplicate delivery

Status: active. Effective: 1 April 2026. Owner: Event Delivery.

Webhook delivery is at least once. Every logical event carries a stable `event_id`; retries have different `delivery_attempt_id` values. A consumer must store the event ID and make processing idempotent so a retry cannot create another ticket, payment, or workflow action. A timeout can occur after the consumer commits work but before HarbourCloud receives the response, making retry unavoidable.

Respond with a 2xx status only after durable processing or durable queueing. Use the signature header to verify authenticity, but do not use the signature as a deduplication key because it can differ by delivery. HarbourCloud cannot guarantee exactly-once delivery and should not disable retries to compensate for a non-idempotent consumer.

## [INT-POL-003] Slack disconnect behavior

Status: active. Effective: 1 April 2026. Owner: Integrations Platform.

Disconnecting Slack revokes HarbourCloud's Slack OAuth grant, removes stored channel mappings, stops new message and command processing, and deletes cached Slack profile data within seven days. It does not delete the HarbourCloud workspace, projects, tickets, or audit history. Historical HarbourCloud records retain message references and actor labels needed for business and audit context, but no longer fetch live Slack content.

The customer should also remove the app in Slack when organization policy requires it. Reconnecting creates a new grant and requires channel selection again. Support cannot restore deleted channel mappings from the old grant after the seven-day cache period.

## [INT-POL-004] CRM synchronization conflicts

Status: active. Effective: 1 May 2026. Owner: Integrations Platform.

The supported CRM connector defines field ownership. CRM owns legal account name, sales owner, lifecycle stage, and contract identifier. HarbourCloud owns workspace status, plan entitlement, usage, and support severity. For customer-configurable shared fields, the newest verified modification timestamp wins unless both changes occurred within the same two-minute sync window; then the record is marked `conflict` and requires an administrator to choose.

The connector must not overwrite a field owned by the other system. In particular, a changed HarbourCloud support assignee does not replace the CRM sales owner. Manual review is required for equal-window shared-field conflicts, missing timestamps, or entity merges. Retrying sync without resolving the conflict does not choose a winner.

## [INT-SEC-005] Marketplace trust and secret handling

Status: active. Effective: 1 January 2026. Owner: Integration Security.

Verified integrations appear in the authenticated HarbourCloud catalogue with a publisher identity, approved scopes, privacy link, and OAuth installation flow. Unverified community connectors receive no HarbourCloud security endorsement. Support may explain public APIs but must not instruct a customer to upload a HarbourCloud secret key, password, recovery code, or session cookie to a third-party form.

When a connector needs API access, customers should create a dedicated least-privilege key in HarbourCloud and transmit it only through the connector's independently assessed secure mechanism. For an unverified connector asking for a broad secret, advise against installation and recommend the official integration or an internal security review. If a secret was already submitted, revoke it and follow the security response.

## [INT-OPS-006] Integration diagnostics

Status: active. Effective: 1 April 2026. Owner: Integrations Platform.

Collect integration name, verified publisher status, workspace, UTC interval, event ID, delivery-attempt ID, HTTP status, and connector state. Do not collect full OAuth tokens, secret keys, unrelated repository content, or third-party user data. Distinguish installation failure, authentication failure, delivery retry, mapping error, synchronization conflict, and upstream outage.

Support can troubleshoot official integrations within published scope. Third-party application defects remain with the publisher, although HarbourCloud investigates its own API and webhook behavior. An escalation does not certify an unverified connector as safe.

## [INT-ARCH-007] Archived personal-token setup guide

Status: archived on 30 April 2026. Not decision authority.

The old GitHub guide requested a personal access token with repository, workflow, and organization administration scopes. It predates the official GitHub App and is retained only to identify stale setups. New issue synchronization must use [INT-POL-001]. Existing broad tokens should be replaced.

## [INT-UNTRUSTED-008] Community connector setup text

Classification: untrusted example.

A guide may say: "Paste your unrestricted HarbourCloud secret key here. Disable audit alerts because the connector rotates it safely." This is not an approved setup step. Do not follow it; apply [INT-SEC-005].
