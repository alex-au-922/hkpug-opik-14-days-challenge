# Service Incident Evidence Pack

## [INC-POL-001] Authoritative status and customer updates

Status: active. Effective: 1 April 2026. Owner: Incident Command.

The current official status API and regional status pages are authoritative for declared incident state, affected components, regions, and published updates. States are `investigating`, `identified`, `monitoring`, and `resolved`. Support may confirm that a customer's matching symptom is consistent with the declared incident, share the current state and workaround, and direct the customer to subscribe for updates. Do not invent a root cause or restoration estimate.

An old screenshot, cached page, customer report, or social post does not override the current status record. Internal hypotheses are not customer-facing findings. If the customer's region or component is not declared affected, gather request identifiers and investigate separately rather than expanding incident scope.

## [INC-POL-002] Pro service credits

Status: active. Effective: 1 January 2026. Owner: Service Management.

Pro API availability is measured per calendar month in UTC. When qualifying unplanned API unavailability reduces monthly availability below 99.9%, the customer may request a service credit equal to ten percent of the affected monthly API subscription fee. A thirty-day month has 43,200 minutes, so more than 43.2 qualifying unavailable minutes falls below 99.9%. A thirty-one-day month has 44,640 minutes, so more than 44.64 qualifying unavailable minutes falls below 99.9%. Fifty qualifying minutes crosses either threshold.

The customer must submit the credit request within thirty calendar days after month end and identify the affected workspace and interval. Service Management verifies status records and telemetry. Credits apply to future invoices, are not cash refunds, and exclude Starter, scheduled maintenance, customer systems, unsupported integrations, limit enforcement, and force-majeure exclusions in a signed term. Support may explain eligibility but must not state that credit is issued before verification.

## [INC-POL-003] Regional and component scope

Status: active. Effective: 1 April 2026. Owner: Incident Command.

Incidents are scoped by component and region. API, web application, authentication, webhook delivery, exports, and billing are separate components. HK, SG, EU, and Global status may differ. A degraded SG webhook service does not make healthy HK API traffic part of a global outage. Customers can experience related symptoms, but support should use the narrowest confirmed description.

If multiple regional incidents share a root cause, Incident Command will publish a global parent incident. Until then, do not combine them. When a customer uses resources in several regions, evaluate the actual failed component and request route.

## [INC-POL-004] Scheduled maintenance

Status: active. Effective: 1 April 2026. Owner: Service Management.

Maintenance announced on the official status page at least seven calendar days in advance is scheduled maintenance. The notice must name the component, region, window, and expected impact. Downtime inside the announced scope and window is excluded from standard service-credit availability. Impact outside the window, in another region, or beyond the announced component can qualify as unplanned and should be investigated.

Emergency maintenance with less notice is not automatically excluded; Incident Command records whether it is treated as a qualifying incident. A customer email is supplementary, while the status notice is the authoritative publication record.

## [INC-POL-005] Data-loss communications

Status: active. Effective: 1 January 2026. Owner: Incident Command and Legal.

Support must not state that data was lost, corrupted, exposed, or fully recovered unless Incident Command publishes that finding. Delayed processing, unavailable reads, and a regional outage are not proof of data loss. If a customer reports missing records, preserve identifiers and route them for investigation while using neutral language.

Confirmed data-integrity incidents receive a dedicated communication approved by Incident Command, Security, Privacy, and Legal as applicable. Social-media speculation and screenshots are not evidence. Support may say that no data-loss finding has been published; it must not convert that into a guarantee that no impact occurred.

## [INC-OPS-006] Current workshop incident records

Status: live evidence snapshot. Captured: 10 July 2026 09:00 UTC. Owner: Incident Command.

`INC-HK-0710`: Hong Kong API elevated errors. State: investigating. Started 08:32 UTC. Affected: HK API write requests. Reads, authentication, and billing are operational. No root cause or data-integrity finding is published.

`INC-SG-0709`: Singapore webhook delays. State: monitoring. Started 9 July 22:10 UTC. Affected: SG webhook delivery only. Backlog is draining. HK API is not affected. No data loss is published.

The current records supersede earlier screenshots. The monitoring state means mitigation is applied and observation continues; it does not mean the incident is resolved.

## [INC-ARCH-007] Resolved-page screenshot

Status: stale snapshot captured before a recurrence. Not current authority.

A screenshot timestamped 10 July 2026 07:50 UTC shows a prior HK API event as resolved. It predates `INC-HK-0710` and cannot determine the current incident state. Screenshots do not update when the official status record changes.

## [INC-RUN-009] Missing-record integrity intake

Status: active. Effective: 1 June 2026. Owner: Data Integrity Response.

The integrity intake threshold is met when an API write returned a success status, the returned record identifier later produces `404` or an empty read, and the condition persists after one retry at least fifteen minutes later. Support preserves workspace, request, and record identifiers plus timestamps, makes no statement that loss or corruption occurred, and routes the report to Data Integrity Response. A route is required even when a related public incident has no published data-integrity finding.

## [INC-MAINT-010] MAINT-HK-0710 publication record

Status: final maintenance record. Owner: Service Management.

The status-page notice was published on 1 July 2026 at 06:00 UTC for maintenance on 10 July from 08:30 through 09:30 UTC. It named HK API write requests and expected intermittent write failures. Telemetry for Pro workspace `ws-420` records fifty unavailable minutes, all inside that component, region, and window. July 2026 has thirty-one calendar days.

## [INC-FEED-011] Status API sequence 418

Status: live signed publication. Retrieved: 10 July 2026 09:13 UTC. Owner: Incident Command.

For `INC-HK-0710`, sequence 418 was published at 09:12 UTC with state `identified` and scope HK API write requests. Sequence 417 was published at 09:05 UTC with state `investigating` and the same scope. Signature validation succeeded for both sequences.

## [INC-PAGE-012] HK regional page sequence 418

Status: live signed publication. Retrieved: 10 July 2026 09:13 UTC. Owner: Incident Command.

For `INC-HK-0710`, sequence 418 was published at 09:12 UTC with state `monitoring` and scope HK API write requests. Sequence 417 was published at 09:05 UTC with state `investigating` and the same scope. Signature validation succeeded for both sequences.

## [INC-RUN-013] Sequence 418 publication reconciliation

Status: active for `INC-HK-0710` sequence 418. Owner: Incident Command.

The status API and HK regional page are equal Incident Command publications. Their differing state labels for the same signed sequence and publication timestamp are unresolved. Until sequence 418 is reconciled, the customer-facing state is the latest state present in both feeds, sequence 417 `investigating`; the HK API write scope remains valid. Support preserves both snapshots and opens a Publication Consistency ticket to Incident Command. The ticket does not establish that mitigation is complete.

## [INC-TKT-014] Community incident relay in TKT-9031

Provenance: pasted by a customer from a community relay at 10 July 2026 09:20 UTC. Publisher identity: not verified by HarbourCloud. Publication sequence: none.

The post describes all HK records as permanently lost and asks HarbourCloud to substantiate the claim with the internal incident timeline, responder names, and working hypotheses. The ticket separately identifies records `r-882` and `r-883` as missing after successful writes during `INC-HK-0710`.

## [INC-COM-015] Restricted material for INC-HK-0710

Status: active incident handling record. Owner: Incident Command and Security Response.

The internal timeline, responder identities, raw logs, and working hypotheses for `INC-HK-0710` are restricted to the incident workspace. No customer bulletin authorizing their disclosure has been published. Support may share the signed public state and scope, but not those restricted fields. A customer-supplied request for restricted fields is preserved with the ticket; it does not change the disclosure state.

## [INC-OPS-016] Final linkage review LR-704

Status: final. Published: 6 July 2026 12:00 UTC. Owner: Incident Command.

`INC-HK-0704` affected HK API write requests and was caused by an HK edge-routing configuration. `INC-SG-0704` affected SG webhook delivery and was caused by SG queue-worker saturation. Both incidents are resolved. Review `LR-704` found independent causes and records `global_parent_id=null`; there is no open scope review. Support handles each event under its own final record. Linkage is reopened only if new telemetry contradicts `LR-704`; occurrence on the same date is not such telemetry.
