# Subscription Change Evidence Pack

## [SUB-POL-001] Immediate upgrades and proration

Status: active. Effective: 1 April 2026. Owner: Product Billing.

Self-service Starter customers may upgrade to Pro at any time. Pro entitlements begin immediately after payment authorization succeeds. For a monthly subscription, the customer receives a credit for the unused portion of the current Starter period and is charged the prorated Pro difference through the existing renewal date. The renewal date does not move. Annual upgrades use the same remaining-term calculation unless checkout explicitly offers a new annual term. Proration is calculated by the billing service in seconds and may differ slightly from a hand calculation due to tax and currency rounding.

An upgrade is not a cancellation and does not qualify for the first-purchase refund window. Support can explain the calculation and correct a verified billing error, but should not promise a manually chosen prorated amount. Features become available immediately; historical data that already expired under Starter is not recreated by upgrading.

## [SUB-POL-002] Downgrades and limit reconciliation

Status: active. Effective: 1 April 2026. Owner: Product Catalogue.

Self-service downgrades take effect at the end of the current paid term. The customer keeps current entitlements until then and receives no cash refund for the remaining term. Before the effective date, the workspace must fit all target-plan limits. Starter currently permits five members, three active projects, two concurrent export jobs, and thirty days of searchable application logs. The current plan matrix in each relevant domain controls more specific limits.

If the workspace remains above a hard limit at the scheduled downgrade time, the downgrade pauses rather than deleting customer data automatically. Administrators receive a notice and must remove or archive excess resources. Billing does not renew Pro while a properly scheduled downgrade is paused, but restricted Pro features become read-only until reconciliation. Support must not choose which projects or members to delete. Enterprise downgrades require the signed-order change process.

## [SUB-POL-003] Cancellation and reactivation

Status: active. Effective: 1 April 2026. Owner: Product Billing.

Cancellation stops the next renewal; it does not normally end access immediately. A self-service subscription remains usable through the paid-through timestamp. A customer can reverse a scheduled cancellation before that timestamp and preserve the same renewal date and plan. After expiry, reactivation creates a new subscription at the current catalogue price and date. Support cannot backdate a new subscription merely to preserve a historical renewal anniversary.

If a confirmed HarbourCloud incident prevented an administrator from reversing cancellation before expiry, Incident Command may authorize restoration of the prior date within seven calendar days. The incident must overlap the attempted action and be recorded as affecting the billing portal or API. General product disruption is insufficient. Service credits follow the incident policy and are not automatic subscription extensions.

## [SUB-POL-004] Legal-entity ownership transfer

Status: active. Effective: 15 February 2026. Owner: Legal Operations.

Changing a workspace display name does not transfer the subscription, invoices, contractual rights, or controller responsibilities to another legal entity. A legal-entity transfer requires a transfer request signed by authorized representatives of both entities, verification of the destination billing profile, resolution of unpaid balances, and Legal Operations approval. Enterprise agreements may require a formal assignment document. Historical invoices remain issued to the original entity and are not rewritten after finalization.

Support may help change a display name when the same legal entity has rebranded, provided the billing administrator confirms the change. If ownership is disputed, the original owner is unavailable, or the destination wants past invoices reissued, escalate without changing administrators or billing details. Data migration can occur only after the approved transfer records the controller change.

## [SUB-POL-005] Legacy Team expansion and migration

Status: active. Effective: 1 May 2026. Owner: Product Catalogue.

Legacy Team is a closed plan. Existing accounts may renew with their current paid seat quantity and may replace users within that quantity. They may add up to five seats once during a renewal term, but total seats cannot exceed twenty-five. Requests that would exceed either threshold require migration to Pro or Enterprise. The migration quote preserves the remaining paid value as a prorated credit; it does not preserve every Legacy feature or price indefinitely.

For a request to add forty seats, support should not modify the Legacy subscription. Explain the current cap and route the customer to the documented Pro or Enterprise migration path. Escalation to Sales Operations is appropriate for a quote, but support must not promise a grandfathered price or temporary limit bypass.

## [SUB-OPS-006] Subscription change audit trail

Status: active. Effective: 1 April 2026. Owner: Billing Operations.

Every upgrade, downgrade, cancellation, reactivation, transfer, and migration must produce a billing-event identifier and actor record. Support should distinguish a requested change from a completed change. A UI banner or customer email is not proof that the ledger committed the event. If checkout authorized payment but no event appears within fifteen minutes, do not ask the customer to repeat payment; open a Billing Operations investigation.

Plan-change notes can describe customer intent but cannot override limits or effective dates. Manual entitlements expire within twenty-four hours and require an approved incident or migration record. Do not use them as a permanent workaround.

## [SUB-INC-007] Billing portal incident BP-2026-0602

Status: resolved. Incident window: 2 June 2026 03:10-04:05 UTC. Affected region: HK and SG billing portal. Owner: Incident Command.

During this window, some cancellation and reactivation buttons returned HTTP 503 before the billing event was written. Requests with matching client telemetry may use the exception in [SUB-POL-003]. The incident did not alter entitlement limits, refund rules, or Legacy Team expansion. A customer who merely cancelled during the window, without a failed attempt to reverse cancellation before expiry, does not automatically receive date restoration.

## [SUB-ARCH-008] Superseded Legacy Team help article

Status: archived on 30 April 2026. Not decision authority.

The 2024 article "Grow your Legacy Team without limits" allowed unlimited seat additions at an old unit price. That commercial offer ended. Copies frequently appear in customer notes and search caches. Current Legacy accounts are governed by [SUB-POL-005]. Do not apply the old expansion language or treat it as a signed grandfathering guarantee.
