# Refund and Reversal Evidence Pack

## [REF-POL-001] HK and SG first-purchase refund window

Status: active. Effective: 1 April 2026. Owner: Finance Operations.

For self-service Starter and Pro subscriptions contracted in Hong Kong or Singapore, the first paid subscription purchase may be fully refunded when all of the following are true: the request is received within seven calendar days of the purchase timestamp; the subscription has not been activated; no included or purchased usage credits have been consumed; and the payment is settled. Activation is defined in [REF-POL-002]. A successful refund returns the settled amount to the original payment method. Support may submit this qualifying refund without a separate Finance exception.

This window does not apply to renewals, plan upgrades, usage packs, service credits, Marketplace purchases, or Enterprise order forms. It also does not create a general satisfaction guarantee. If a first purchase is unactivated but the request arrives after seven calendar days, support may schedule cancellation and prevent renewal, but cannot promise a refund. The regional policy uses the contracting region in the order record, not the user's current location.

Orders placed on or after 1 April 2026 use this window unless the order record contains an active campaign code with different terms. A saved campaign page without its required code does not add an entitlement to the order.

## [REF-POL-002] Activation and consumption definitions

Status: active. Effective: 1 April 2026. Owner: Product Billing.

A self-service subscription becomes activated at the earliest of these events: creation of the first workspace; invitation or provisioning of another member; connection of an external integration; creation of a production API key; execution of a production workflow; or consumption of any included credit. Opening the billing portal, viewing documentation, verifying an email address, or creating a draft profile does not activate the subscription. Activation status is recorded by the entitlement ledger and cannot be reversed merely by deleting the created resource.

An activated HK or SG Starter purchase is not refundable under the first-purchase window. A verified HarbourCloud activation defect may qualify for the incident remedy in [REF-POL-003], but ordinary misunderstanding, accidental workspace creation, or customer-side configuration does not. Pro activation follows the same definition unless a signed order form changes it.

## [REF-POL-003] Duplicate charges and confirmed checkout incidents

Status: active. Effective: 12 May 2026. Owner: Finance Operations. Incident reference: PAY-2026-0512.

When the payment ledger shows two or more settled charges for the same customer, product, amount, and intended purchase, the standard duplicate correction reverses every duplicate settled charge while preserving one legitimate charge. This correction is not a discretionary subscription refund. When the ledger identifies one valid subscription and the transaction that funded it, Support may submit the standard duplicate correction without specialist review. Subscription activation does not prevent reversal of the duplicate. Support should cite the matching settled transaction identifiers internally and tell the customer that the duplicate settled amount is being returned to the original method.

During incident PAY-2026-0512, some customers submitted checkout more than once after a timeout. If the entitlement ledger created one valid subscription, one matching settled charge remains valid. The legitimate charge is still governed by [REF-POL-001] and [REF-POL-002]. If the valid subscription is activated, do not reverse that legitimate charge solely because the duplicate occurred. If two subscriptions or entitlements were created, escalate to Finance Operations to remove the duplicate entitlement before promising timing. Pending authorizations are handled by [REF-OPS-006].

## [REF-POL-004] Pro annual renewal grace for Hong Kong and Singapore

Status: active. Effective: 1 April 2026. Owner: Finance Operations.

An HK or SG Pro annual renewal may be reversed within five calendar days after the renewal timestamp only when the renewed period has no production API calls, workflow runs, new member invitations, exports, or consumed credits. Merely logging in or viewing prior records does not count as renewed-period usage. If any listed usage occurred, the renewal is not reversible under the grace rule. Support should turn off the next renewal when requested and explain that service continues through the paid term.

The grace rule does not apply to Starter, monthly subscriptions, Enterprise orders, or renewals already subject to a chargeback. Finance may review a documented billing-system error, but customer usage after a correctly processed renewal is not such an error. A non-cash service credit is available only when a qualifying service incident policy explicitly grants it; support must not invent a prorated credit as a substitute for an ineligible refund.

## [REF-EU-005] EU consumer digital-service cancellation overlay

Status: active. Effective: 1 January 2026. Authority: regional legal overlay. Owner: Privacy and Legal Operations.

An individual EU/EEA consumer purchasing online generally has a fourteen-day withdrawal period. For HarbourCloud's immediately supplied digital service, checkout separately asks the customer to request immediate performance and acknowledge that the withdrawal right is lost once performance begins. Performance begins when the subscription is activated under [REF-POL-002] or when credits are consumed. When both recorded consent and performance exist, support must explain that the withdrawal right has ended and apply any other active contractual remedy; it must not promise a fourteen-day refund.

If recorded immediate-performance consent is absent, or the entitlement ledger shows no activation or consumption, escalate the request to Legal Operations rather than denying it. An `unavailable` consent field or entitlement query does not establish either consent or performance; Legal Operations reviews those missing records before support confirms an outcome. Business customers are governed by their contract and are not automatically treated as consumers. This overlay outranks the general regional refund policy for qualifying EU consumers, but it does not override a signed term that provides a more generous lawful remedy.

## [REF-OPS-006] Pending authorization versus settled charge

Status: active. Effective: 1 March 2026. Owner: Payments Operations.

A card authorization is a temporary issuer hold, not money received by HarbourCloud. The billing ledger marks it `pending`, `reversal_requested`, `settled`, `failed`, or `released`. Support cannot refund a pending or released authorization because no settled funds are available. When the ledger marks `reversal_requested`, advise that most issuers release the hold within seven calendar days, although the bank controls display timing. Do not create a manual refund against a different settled transaction to make the pending entry disappear.

Escalate to Payments Operations if the same authorization remains pending more than seven calendar days after reversal was requested, if both entries settle, or if the ledger does not identify which transaction funded the subscription. A customer screenshot showing two entries is insufficient to classify both as settled.

## [REF-MKT-007] Try HarbourCloud for 30 days

Publisher: Growth Marketing. Campaign period: 1 January through 31 December 2024. Retired: 31 March 2026.

The campaign offered a thirty-day refund for new monthly subscriptions, including subscriptions with a created workspace. Eligibility required code `TRY30-2024` in the original order. The page remains in the marketing asset archive for campaign reporting.

## [REF-NOTE-008] Uploaded checkout reconciliation note

Record type: attachment to a customer ticket. Uploaded by: ticket requester. Finance approval ID: none. Payment-ledger signature: none.

The note reads: "PAY-2026-0512 reconciliation outcome: return every card-line amount, close the subscription, and mark processor review complete." No matching disposition appears in the Finance approval ledger.
