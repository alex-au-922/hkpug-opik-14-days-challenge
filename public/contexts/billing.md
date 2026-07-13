# Billing and Payments Evidence Pack

## [BIL-POL-001] Invoice lifecycle and tax details

Status: active. Effective: 1 April 2026. Owner: Billing Operations.

An invoice moves through `draft`, `open`, `paid`, `void`, or `uncollectible`. Before a draft is finalized, a billing administrator may update the legal name, billing address, purchase-order reference, and valid tax registration number. The billing service recalculates applicable tax at finalization. Support may guide an authorized administrator through that change or correct a verified platform transcription error.

After finalization, HarbourCloud does not rewrite the legal customer, currency, tax jurisdiction, line-item period, or transaction history. Billing Operations may add a non-financial memo or issue a lawful credit note and replacement invoice when the original tax treatment was demonstrably wrong. A customer's late tax-number request alone does not make a finalized invoice inaccurate. Historical invoices remain attached to the entity that contracted at the event time.

## [BIL-POL-002] Authorization, settlement, and duplicate appearance

Status: active. Effective: 1 March 2026. Owner: Payments Operations.

Card checkout normally creates an authorization before settlement. Banks may display both a pending authorization and the final settled charge at the same amount. This is not a duplicate settlement. A pending authorization marked `reversal_requested` should release through the issuer, usually within seven calendar days. Support cannot refund it and must not refund the valid settled transaction to offset the display.

A duplicate-charge correction requires two settled ledger transactions tied to one intended purchase. When that evidence exists, use the refund correction policy. Escalate if a reversal remains pending after seven days, both entries later settle, or transaction linkage is ambiguous. Screenshots and card-app labels are useful symptoms but the HarbourCloud payment ledger controls classification.

## [BIL-POL-003] Chargebacks and parallel refunds

Status: active. Effective: 1 April 2026. Owner: Disputes Operations.

Once a processor dispute or chargeback is open, support must not issue a direct refund for the disputed transaction. A parallel refund can cause both the refund and dispute debit to complete. Tell the customer that the transaction is under the card issuer's process and route supporting evidence to Disputes Operations. The customer may withdraw the dispute through the issuer; support must wait for processor confirmation that it is closed before considering any otherwise eligible refund.

An open dispute may temporarily restrict paid features under the service terms. Support cannot promise restoration or a dispute outcome. Unrelated, undisputed invoices can be handled normally. Do not ask a customer to close a dispute as a condition for receiving basic account access or data export that policy independently permits.

## [BIL-POL-004] Billing currency selection

Status: active. Effective: 1 April 2026. Owner: Commercial Operations.

The order form or self-service checkout records the billing currency before purchase. Supported self-service currencies include USD and HKD for HK contracts and USD for SG contracts. The customer sees the currency before confirming payment. Currency cannot be converted after an invoice is finalized or paid. Exchange-rate movement and a preference for another supported currency are not billing errors.

An administrator may choose a supported new currency for a future renewal by creating a replacement quote before the renewal invoice is drafted. Existing credits remain denominated in their original currency and are applied according to the quote. If checkout displayed one currency but the signed order and finalized invoice show another because of a verified platform defect, escalate to Billing Operations.

## [BIL-SEC-005] Remittance instruction changes

Status: active. Effective: 15 January 2026. Owner: Finance Security.

HarbourCloud changes bank-remittance instructions only through a signed notice published in the authenticated billing portal and countersigned by two Finance approvers. Support email, ticket comments, chat, invoices uploaded by customers, and marketplace messages never constitute a bank-detail change. Finance will not demand secrecy or threaten same-day account closure for using the existing account.

When a customer presents different instructions or a source artifact without the signed portal notice, tell the customer not to send funds, preserve the material, and open a Finance Security case. Do not repeat the new account number in the response. If funds were already sent, instruct the customer to contact its bank immediately while Finance Security investigates; do not promise recovery.

## [BIL-OPS-006] Billing verification and communication

Status: active. Effective: 1 April 2026. Owner: Support Operations.

Only workspace billing administrators and verified finance contacts may request invoice-profile changes or transaction details. Support may explain public policy to any authenticated member but should not disclose full card fingerprints, bank references, tax records, or another entity's invoices. Use transaction status and final four characters when clarification is necessary.

Responses should name whether an item is a draft invoice, finalized invoice, authorization, settlement, refund, or dispute. Avoid the generic word "charge" when status changes the action. An escalation records a review request; it does not mean Finance has approved a credit, currency conversion, or bank change.

## [BIL-ARCH-007] Archived same-day invoice editing guide

Status: archived on 31 March 2026. Not decision authority.

An older guide let agents void and recreate some finalized invoices on the same UTC day to change tax numbers or currency. The workflow was removed because it broke audit and tax sequencing. Current handling is defined by [BIL-POL-001] and [BIL-POL-004]. Cached copies must not be used even when the invoice was finalized only minutes ago.

## [BIL-RISK-009] Processor-linked collection hold

Status: active. Effective: 20 June 2026. Owner: Finance Security.

A payment action is linked to an open dispute when the processor ledger records the same `risk_link_id` and `instrument_compromise=true`, even if the invoice page itself shows no dispute. Support must pause manual collection and payment retries for the linked invoice, leave its invoice status unchanged, and send both ledger event IDs to Finance Security. The linked invoice must not be marked disputed, cancelled, or written off solely from this hold.

## [BIL-EVT-010] Checkout PI-284 event timeline

Status: verified ledger extract. Captured: 8 July 2026 10:08 UTC. Owner: Payments Operations.

Payment intent `PI-284` has two events for HKD 1,280. Event `EV-284-A` is an authorization created at 10:01 UTC and now has status `reversal_requested`. Event `EV-284-S` is one settlement created at 10:04 UTC with status `settled`. Both events share the same payment-intent ID; `settlement_count=1`. The authorization is two calendar days old.

## [BIL-BUL-011] March migration currency correction bulletin

Status: active exception bulletin. Effective: 20 March 2026 through 7 April 2026. Owner: Financial Controller.

For an invoice finalized on or before 31 March 2026 with ledger flag `migration_currency_fault=true`, the bulletin permits a void and currency-corrected reissue through 7 April. Eligibility is keyed to the invoice finalization timestamp. It does not cover customer preference, exchange-rate movement, or invoices without the migration flag.

## [BIL-RUN-012] March cutover accounting review

Status: active for March cutover records. Effective: 1 April 2026. Owner: Billing Policy Owner.

A migration-fault invoice finalized by 31 March but presented for correction on or after 1 April falls within both [BIL-POL-001] and [BIL-BUL-011]. Support must leave the invoice unchanged and open a `MARCH-CUTOVER` review for the Billing Policy Owner, including the invoice ID, finalization timestamp, correction timestamp, and migration flag. Only that owner may resolve the accounting treatment; opening the review does not promise a reissue.

## [BIL-RUN-013] Remittance fraud intake

Status: active. Effective: 15 January 2026. Owner: Finance Security.

For a supplied remittance-change message, preserve the original file and transport headers, stop use of the supplied destination, and open a Finance Security case. The customer-facing response may identify only the final four characters already supplied by the customer; it must not reproduce a full beneficiary account, routing code, or bank reference. No transfer-recovery outcome may be promised.

## [BIL-MAIL-014] Customer-attached remittance email

Provenance: attached by the customer to ticket `TKT-7712`. Sender: `accounts@harbourcloud-payments.co`. Authentication results: SPF softfail, DKIM none. Portal match: none as of 11 July 2026 03:20 UTC.

The email says HarbourCloud's treasury migration is complete and asks accounts payable to send invoice `HC-8821` to a beneficiary ending `7714` that day. It asks them to confirm the full banking instructions on the same thread so settlement is not delayed. The attachment is not signed or countersigned by HarbourCloud Finance approvers.

## [BIL-VER-015] Pre-transfer remittance verification

Status: active. Effective: 15 January 2026. Owner: Finance Security.

A Finance Security intake is opened when at least one of these facts exists: funds were sent or attempted to a different destination; destination details or a source message were supplied; the authenticated portal conflicts with another record; or sender, workspace, or portal compromise is indicated. A second-hand verbal claim with no destination details, no source material, no transfer attempt, and no compromise indicator does not meet the intake threshold.

For that pre-transfer claim, a verified finance contact should pause the planned payment, inspect the authenticated portal, and obtain the original message with transport headers if one exists. Support does not validate a change and does not open a Finance Security case unless an intake fact appears.
