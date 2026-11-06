# FrappeOps Development

## Prerequisites

- Existing Frappe bench (this project targets Frappe v16+)
- Dedicated site: `frappeops.local`
- Do not develop against production customer sites

## Setup

```bash
cd /home/frappe/frappe-bench
# app already under apps/frappeops
bench --site frappeops.local migrate
bench --site frappeops.local clear-cache
```

Access: `http://frappeops.local` (requires `/etc/hosts` → `127.0.0.1 frappeops.local`).

## Coding standards

- Follow Frappe conventions for DocTypes, hooks, and permissions.
- Put domain logic in `frappeops/services/`.
- Use structured argv for subprocesses — never shell string concatenation.
- Redact secrets before logging or storing operation output.
- Feature-flag incomplete functionality; label UI “Not implemented” when needed.
- Prefer small, reviewable changes.

## Safe commands (ok without extra approval)

`bench version`, `list-apps`, `list-sites`, read-only discovery, tests on `frappeops.local`.

## Stop and ask

`drop-site`, `uninstall-app`, production nginx/SSL/DNS/firewall changes, DB restore/drop, `bench update` on shared benches, destructive migrations against protected sites.

## Tests

```bash
bench --site frappeops.local run-tests --app frappeops
```

Never run destructive tests against protected ERPNext sites.
