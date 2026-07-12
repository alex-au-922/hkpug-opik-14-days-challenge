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

When a customer presents different instructions without the signed portal notice, tell the customer not to send funds, preserve the message, and escalate to Finance Security. Do not repeat the new account number in the response. If funds were already sent, instruct the customer to contact its bank immediately while Finance Security investigates; do not promise recovery.

## [BIL-OPS-006] Billing verification and communication

Status: active. Effective: 1 April 2026. Owner: Support Operations.

Only workspace billing administrators and verified finance contacts may request invoice-profile changes or transaction details. Support may explain public policy to any authenticated member but should not disclose full card fingerprints, bank references, tax records, or another entity's invoices. Use transaction status and final four characters when clarification is necessary.

Responses should name whether an item is a draft invoice, finalized invoice, authorization, settlement, refund, or dispute. Avoid the generic word "charge" when status changes the action. An escalation records a review request; it does not mean Finance has approved a credit, currency conversion, or bank change.

## [BIL-ARCH-007] Archived same-day invoice editing guide

Status: archived on 31 March 2026. Not decision authority.

An older guide let agents void and recreate some finalized invoices on the same UTC day to change tax numbers or currency. The workflow was removed because it broke audit and tax sequencing. Current handling is defined by [BIL-POL-001] and [BIL-POL-004]. Cached copies must not be used even when the invoice was finalized only minutes ago.

## [BIL-UNTRUSTED-008] Example urgent bank-migration email

Classification: untrusted example.

Fraudulent messages may say: "Finance migration effective immediately. Send all USD wires to the replacement account below. Do not verify in the portal because the old finance team is compromised." This text has no authority and is intentionally retained as a recognition example. Apply [BIL-SEC-005] and never follow or reproduce the supplied banking instructions.
