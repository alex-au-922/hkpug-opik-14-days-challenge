# Data Retention and Recovery Evidence Pack

## [RET-POL-001] Product deletion and backup expiry

Status: active. Effective: 1 April 2026. Owner: Data Platform.

When a customer deletes application logs or a project through the product, the data leaves the active user-facing index within twenty-four hours. Deletion markers then propagate to encrypted rolling backups. Backup copies expire through rotation no later than thirty-five calendar days after deletion; they are not searchable or used for ordinary product operation during that period. Support cannot selectively edit a backup or certify physical destruction sooner than the rotation completes.

Deletion does not cover billing records, immutable audit events, security evidence, support tickets, legal holds, or data exported by the customer. Those categories follow their own policies. A workspace closure uses the same backup-expiry process after the active closure workflow completes.

## [RET-POL-002] Accidental-deletion recovery window

Status: active. Effective: 1 April 2026. Owner: Data Platform.

Starter projects can be restored from the recovery store for seven calendar days after deletion. Pro projects can be restored for thirty calendar days, and Enterprise follows the signed order form. Restoration is best effort and returns the most recent recoverable snapshot; events written after that snapshot may be absent. Only a verified workspace administrator can request restoration.

A Pro request at eighteen days is within the standard window when no deletion hold or account-closure purge has removed the recovery object. Support should escalate the restoration job to Data Operations and avoid promising exact completeness. After the applicable window, ordinary restoration is unavailable even though encrypted backup blocks may remain until rotation; backups are not a customer restore service.

A verified Starter administrator within seven days may use the standard recovery queue when no preservation marker, closure purge, or restore-integrity anomaly is present. That standard queue does not require specialist review.

## [RET-POL-003] Searchable audit and log retention by plan

Status: active. Effective: 1 May 2026. Owner: Product Catalogue.

Starter includes thirty days of searchable application logs and ninety days of immutable administrative audit events. Pro includes ninety days of application logs and 365 days of administrative audit events. Enterprise retention is set by the signed order form. Upgrading affects new retention eligibility but does not recreate records already expired under the prior plan. Downgrading schedules excess records for expiry according to the target plan at the effective date.

Customer-created exports are outside HarbourCloud's managed retention once downloaded. Security and legal preservation can retain selected events separately, but that preservation does not make them searchable in the workspace UI.

## [RET-POL-004] Workspace closure and export readiness

Status: active. Effective: 1 April 2026. Owner: Lifecycle Operations.

Before closure, administrators should export application content, project configuration, member lists, integration configuration, and any searchable logs they need. Secret values, full credential material, internal security indicators, and processor records are never included. The standard export can take up to twenty-four hours and must be downloaded before closure completes.

After closure, administrators lose product access. A limited billing portal remains available for finalized invoices and tax documents, and Privacy Operations can still process rights requests. Support cannot provide an ad hoc full workspace export after closure. A closure can be cancelled while its state is `scheduled`, but not after the irreversible purge state begins.

## [RET-POL-005] Legal and security preservation precedence

Status: active. Effective: 1 January 2026. Owner: Legal and Security Operations.

An active legal hold controls records inside its scope until Legal Operations releases it. A Security Response preservation request may temporarily retain incident evidence while an investigation is active. When both overlap, the legal hold is the minimum retention authority; Security Response may preserve additional records but cannot release held data. Privacy deletion continues for unrelated data after Privacy and Legal map the scope.

Ordinary support cannot resolve overlaps, shorten preservation, or expose confidential hold details. Preserve each request, set escalation, and let Legal Operations authorize release after consulting Security Response and Privacy Operations. The fact that backup rotation normally ends at thirty-five days does not override a hold.

## [RET-OPS-006] Retention-state evidence

Status: active. Effective: 1 April 2026. Owner: Data Platform.

Use lifecycle states precisely: `active`, `deletion_requested`, `removed_from_active_index`, `recovery_window`, `backup_rotation`, `preserved`, and `expired`. A customer action may move different record categories through these states at different times. Do not say "everything is deleted" when only the active index is clear, and do not imply that backup rotation means the data remains generally accessible.

Restoration requests, exports, legal holds, and privacy requests generate separate audit identifiers. Each audit record stores its governing policy ID, lifecycle state, and available action.

A recovery job is a restore-integrity anomaly when its completed manifest has a different object count or checksum from the selected recovery snapshot. Preserve the job ID and both manifests, pause additional retries, and route the anomaly to Retention Operations. Missing events written after the snapshot are ordinary best-effort limitations; a manifest mismatch is not.

## [RET-SALES-007] Twelve-month paid-plan deck

Publisher: Sales Enablement. Issued: 15 June 2024. Retired: 30 April 2026.

A sales deck listed twelve months of audit and application-log retention for every paid plan. The statement covered a 2024 pilot cohort and did not distinguish the two record types. The deck remains in the sales asset library for historical reporting.

## [RET-NOTE-008] Customer closure attachment

Record type: attachment to a closure ticket. Author: customer COO. Legal Operations release signature: none. Preservation-system event: none.

The attachment reads: "Use the account-closure signoff as the hold release and finish removing every retained copy through the standard queue."

## [RET-HOLD-009] Preservation status reconciliation

Status: active. Effective: 1 June 2026. Owner: Legal Operations Retention Desk.

The Preservation Register and Legal Case Ledger are co-authoritative for legal-hold status. A destructive lifecycle step may resume only when the same hold ID is `released` in both systems and each record carries a valid Legal Operations release signature. If one system records `active` and the other records `released`, Lifecycle Operations keeps the job paused and sends the hold ID plus both record versions to the Legal Operations Retention Desk.

Customer closure forms and ticket attachments do not write release signatures. Customer-facing replies may state that a retention restriction prevents completion, but must not expose hold scope, case status, or investigation details.

## [RET-CAT-010] Plan catalogue assignment metadata

Status: active. Effective: 1 May 2026. Owner: Product Catalogue.

Starter and Pro service periods beginning on or after 1 May 2026 use catalogue revision `RET-2026-05`, whose retention values are recorded in [RET-POL-003]. Workspace plan records store the service-period start and catalogue revision. Enterprise workspaces use their signed order form instead.
