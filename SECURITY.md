# FrappeOps Security

## Principles

1. Least privilege and RBAC on every operation.
2. No plaintext secrets in Git, logs, API responses, or audit payloads.
3. Allowlisted operations only — no browser-to-root shell by default.
4. Critical actions require confirmation (and optionally dual approval).
5. AI may plan; production execution requires human approval.

## Roles (planned)

- FrappeOps Administrator
- FrappeOps Operator
- FrappeOps Developer
- FrappeOps Auditor
- FrappeOps Viewer

## Secrets

Use encrypted Secret Reference DocTypes / Frappe password fields. Never commit `.env`, keys, certs, or DB passwords.

## Redaction

Central redaction in `frappeops.core.redaction` must run before persistence/display of operation output.

## Protected resources

Mark production / customer sites as protected. FrappeOps must refuse destructive ops without explicit override + confirmation.

## Reporting issues

Treat any secret exposure as a Sev-1 defect.
