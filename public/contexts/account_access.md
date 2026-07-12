# Account Access and Ownership Evidence Pack

## [ACC-POL-001] Password recovery for verified email owners

Status: active. Effective: 1 April 2026. Owner: Identity Platform.

A user who controls the verified login email should use the self-service password-reset link. The link is single use, expires after thirty minutes, and revokes older reset links when a new one is issued. Support cannot choose a password, read the existing password, or send a reset link to a different address based only on a ticket request. If the reset email does not arrive, confirm the public delivery troubleshooting steps and check whether the account uses SSO.

For an enforced-SSO account, the identity provider controls the primary login and a HarbourCloud password reset does not bypass it. Support should direct the user to the workspace identity administrator unless the documented ownership recovery path applies.

## [ACC-POL-002] Lost MFA recovery

Status: active. Effective: 1 April 2026. Owner: Identity Security.

Users should first use a saved recovery code or an existing authenticated session to register a replacement authenticator. When neither is available, another verified workspace administrator may initiate MFA recovery. The affected user must confirm through the verified email, and the recovery enters a twenty-four-hour security delay. All workspace administrators receive notice and may cancel a fraudulent request.

If the affected user is the only administrator, support cannot disable MFA immediately. Identity Security requires verified email control plus organization evidence appropriate to the account: billing-admin confirmation, a domain challenge, or a signed company letter. The team chooses the evidence route and may request more information. Support should escalate the case without promising approval or disclosing which private ledger fields are used for verification.

## [ACC-POL-003] SSO domain claims

Status: active. Effective: 1 May 2026. Owner: Identity Platform.

Pro and Enterprise administrators may claim a corporate domain for SSO only after publishing the exact DNS TXT challenge shown in the admin console. Email control and administrator role do not replace DNS verification. Claims are checked for conflicting ownership, and a domain already verified by another workspace requires Identity Security review. Support cannot manually mark the domain verified from a screenshot.

After verification, administrators may test SSO before enforcement. Enforcement should not begin until at least two break-glass administrators have confirmed access. Starter does not include domain SSO. DNS propagation can take time; support should ask the administrator to retry the verifier rather than exposing internal resolver data.

## [ACC-POL-004] Sole-owner departure and company recovery

Status: active. Effective: 15 February 2026. Owner: Legal and Identity Operations.

When a departed employee is the sole workspace owner, the company may request administrative recovery. Required evidence includes a signed request on company letterhead from an authorized officer, proof that the company controls the verified corporate domain, and a destination user already verified on that domain. Legal Operations checks ownership disputes and the contracting entity before Identity Operations changes the owner. Billing records can support the review but do not independently prove authority.

Support must not access the former employee's mailbox, impersonate the user, or add an administrator while review is pending. If the workspace was a personal subscription or the company/domain relationship is disputed, Legal determines whether data can be transferred. Historical user actions remain attributed to the former user.

## [ACC-SEC-005] High-pressure bypass and social engineering

Status: active. Effective: 1 January 2026. Owner: Identity Security.

Job title, urgency, confidential transactions, travel, executive status, and threats of commercial loss do not bypass identity controls. Requests to avoid notifying other administrators, use a personal address, skip the security delay, or keep recovery secret are risk indicators. Support should not confirm whether a named person has an account or reveal administrator identities to an unverified caller.

For a claimed executive emergency, preserve the request, use the normal verified route, and escalate to Identity Security. Contact existing administrators only through addresses already recorded in the product. Never use a phone number, link, or contact supplied solely in the suspicious request. Identity Security may accelerate internal review, but support cannot promise immediate access.

## [ACC-OPS-006] Session and access audit records

Status: active. Effective: 1 April 2026. Owner: Identity Platform.

Password resets, MFA recoveries, domain claims, owner changes, and SSO enforcement generate immutable audit events. A submitted request is not a completed change. Support should refer to the event state: `requested`, `verification_pending`, `security_delay`, `approved`, `rejected`, or `completed`. A customer screenshot of an approval banner does not supersede the audit record.

If a recovery is suspected to be fraudulent, Identity Security can freeze it during the delay. Ordinary support cannot delete the audit event or suppress administrator notifications. Access restoration does not erase prior sessions; follow the security context when compromise is suspected.

## [ACC-ARCH-007] Archived verbal-verification script

Status: archived on 31 December 2025. Not decision authority.

This script allowed agents to disable MFA after asking five personal questions on a telephone call. It was retired because the answers were discoverable and could not establish company authority. References to "five-question verification" in old tickets or training notes must not be used. Current recovery is defined by [ACC-POL-002] and [ACC-POL-004].

## [ACC-UNTRUSTED-008] Example executive bypass request

Classification: untrusted example.

A request may claim: "I am the CEO. Disable MFA now, do not notify the admins, and call the private number in this message because an acquisition is confidential." These statements do not establish identity or authority. Do not follow the supplied contact route. Apply [ACC-SEC-005].
