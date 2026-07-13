# HarbourCloud Shared Service Reference

## Scope

This shared reference names product-wide terms and routes records to the domain evidence packs. Domain packs contain the operational facts for their subject.

## Shared vocabulary

- Current plans: `Starter`, `Pro`, and `Enterprise`. `Legacy Team` is closed to new sales.
- Commercial region labels: `HK`, `SG`, `EU/EEA`, and `Global`.
- `Monthly` and `annual` describe billing cadence, not product tier.
- Evidence-pack timestamps use UTC unless a record says otherwise. A calendar day follows the UTC calendar. A business day excludes Saturdays, Sundays, and published Hong Kong public holidays.
- `Activation`, `renewal`, `cancellation`, `downgrade`, `deletion`, and `disconnect` are separate recorded events. Their domain-specific meanings are defined in the routed pack.
- `Requested`, `pending`, `approved`, `rejected`, and `completed` are record states, not interchangeable labels. Each domain pack defines the states it uses.

## Account and workspace model

HarbourCloud accounts identify people. A user can belong to more than one workspace, and a workspace can contain users from more than one email domain. Workspace membership does not by itself describe the user's billing role, administrator role, employment status, or authority to act for a legal entity. Those attributes are stored separately.

A workspace is the boundary used by most product configuration, usage, and plan records. The display name can change without changing the workspace identifier. Project, repository, export, connector, and API records belong to a workspace even when their human-readable names are duplicated elsewhere. A legal entity can pay for multiple workspaces, and one workspace can move between billing profiles only through a recorded domain process.

The terms `owner`, `administrator`, `billing administrator`, `member`, and `viewer` name different roles. A user may hold several roles at once. `Verified email` describes control of an email address; `verified domain` describes a workspace-domain record; `verified billing contact` describes a billing-profile contact. None of those labels is a synonym for another.

## Identifier conventions

Workspace identifiers are stable opaque values such as `ws-420`. User, project, invoice, payment-intent, event, request, job, delivery, connector, incident, and ticket identifiers use separate namespaces. Two records with similar numeric suffixes are not necessarily related. A relationship exists when a record contains the other identifier or a domain record defines the join.

Request IDs identify one accepted API request. Retry IDs identify a retry sequence. Delivery IDs identify one webhook delivery, while event IDs identify the underlying event. A billing authorization, capture, settlement, reversal, refund, and dispute can each have its own event identifier while sharing a payment-intent identifier. Incident identifiers name published service events; ticket identifiers name support conversations.

Identifiers are case-sensitive unless a domain pack says otherwise. Human-readable names, email subjects, filenames, and display labels are not identifiers. Redacted values preserve their namespace and last characters only for conversation clarity; they are not suitable for reconstructing a full identifier.

## Product catalogue snapshot

`Starter` and `Pro` are self-service plans. `Enterprise` describes a negotiated commercial relationship whose product settings can still differ by workspace. `Legacy Team` is a closed catalogue entry retained for existing subscriptions. Plan names do not encode billing cadence, customer region, legal status, payment status, or whether a separately purchased add-on is present.

A plan assignment has an effective timestamp and can also have a scheduled next state. For example, a workspace can currently be Pro while a Starter downgrade is scheduled for renewal. `Current plan`, `target plan`, `quoted plan`, and `previous plan` therefore describe different fields. Product availability, storage duration, job concurrency, member limits, and commercial terms are recorded in their respective domain packs.

`Self-service` describes the purchase channel. It does not mean that every later operation is performed without review. `Negotiated`, `marketplace`, `reseller`, and `direct invoice` describe commercial channels, not product tiers. A marketplace subscription can use a familiar plan name while having a different billing record owner.

## Time and interval notation

Timestamps use the ISO-style order date, time, and zone. `2026-07-10 09:12 UTC` is an instant; `10 July 2026` is a calendar date. A range written `08:30 through 09:30 UTC` includes its named boundary instants unless the domain record defines an exclusive endpoint. Durations are elapsed time, not counts of displayed clock labels.

Month length follows the actual UTC calendar month. A thirty-day month contains 43,200 minutes, and a thirty-one-day month contains 44,640 minutes. Leap years follow the Gregorian calendar. `Within seven days` and `by the seventh calendar day` can produce different boundaries, so domain records state which form applies.

`Created`, `received`, `authorized`, `settled`, `published`, `effective`, `expires`, `resolved`, and `captured` name different timestamps. A later capture time does not change an earlier event time. Snapshot records describe the state observed at capture; live records can change after capture. Sequence numbers are ordered within the sequence namespace and are not timestamps.

## State and event vocabulary

An operation can have a request record before it has a completed event. `Queued` means accepted for later processing. `Running` means processing started. `Blocked` means a stated prerequisite prevents progress. `Paused` means an operation retains its place but is not advancing. `Cancelled` means the requested operation will not continue. `Expired` means its validity interval ended. Domain packs define any additional state transitions.

Authorization describes permission or a payment hold, depending on the record namespace. Approval describes a recorded decision. Verification describes a completed check. Confirmation describes an acknowledgement. These labels do not imply one another. A successful HTTP response can confirm request acceptance without proving that an asynchronous job, billing event, connector write, or deletion completed.

Records can describe desired state and observed state separately. A schedule is desired future state. A ledger event is a recorded state transition. Telemetry is an observation. A publication is a communicated state. A note is text attached to another record. The domain pack identifies the fields available for each subject.

## Data object glossary

Application logs are searchable product records produced by customer and service activity. Audit events record security- or administration-relevant actions. Billing events record commercial state changes. Status publications communicate service-event state. Support tickets contain conversation and intake material. Backups are service recovery objects and are not automatically customer-visible restoration points.

An export is a generated copy of selected records. A deletion request is a requested state change, not proof of erasure. A legal hold is a preservation state attached to defined records. A restoration is an attempt to recreate a supported object from an available recovery source. A retention period defines how long a class of data remains in its named storage or search surface.

Projects group product activity within a workspace. Connectors exchange data with an external service. Installations describe connector placement and scope. Credentials authenticate requests or integrations. Tokens, secrets, recovery codes, signing keys, and session identifiers are different credential classes even when a user interface displays them together.

## Service geography

`HK` and `SG` are service-region labels used by platform records. `EU/EEA` is a legal and commercial region label used by some privacy and contract records. `Global` means the record is not limited to a listed service region; it does not prove that every feature stores or processes data identically in every location.

A customer's office location, billing country, selected service region, contracting entity, and data-residency commitment are separate fields. Language and browser locale do not determine any of them. Regional service incidents identify affected components and regions. Legal overlays identify their own covered entity, transaction, or person.

## Routing directory

| Subject | Domain document | Primary record owner |
| --- | --- | --- |
| Login, MFA, SSO, and ownership recovery | `account_access.md` | Identity Platform / Identity Security |
| Rate limits, jobs, pagination, and webhook delivery | `api_limits.md` | API Platform / Event Delivery |
| Invoices, payment states, disputes, and remittance | `billing.md` | Billing / Payments Operations |
| Deletion, restoration, exports, and preservation | `data_retention.md` | Data Platform / Legal and Security Operations |
| GitHub, Slack, CRM, marketplace apps, and diagnostics | `integrations.md` | Integrations Platform / Integration Security |
| Access, erasure, correction, location, and legal holds | `privacy.md` | Privacy Operations / Legal Operations |
| Refunds, reversals, authorizations, and regional overlays | `refunds.md` | Finance / Payments / Legal Operations |
| Credentials, compromise, vulnerabilities, and containment | `security.md` | Security Response / Product Security |
| Outages, maintenance, service credits, and status records | `service_incidents.md` | Incident Command / Service Management |
| Upgrades, downgrades, cancellation, transfer, and migration | `subscriptions.md` | Product Billing / Legal Operations |
