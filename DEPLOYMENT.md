# FrappeOps Deployment

## Development (current)

1. Install app on dedicated site `frappeops.local` only.
2. Point local DNS via `/etc/hosts` — do not publish externally during development.
3. Do not install on existing ERPNext customer sites.
4. Prefer coexistence: additional site on the same bench, FrappeOps-owned nginx snippets only.

## Production (later)

Do not deploy until tests, security review, backup/restore verification, and monitoring are in place. See master spec §99–§132.

## Coexistence

If the host already runs ERPNext:

1. Discover first.
2. Add control site — do not reinstall the server.
3. Preserve existing sites and nginx.
4. Validate (`nginx -t`) before reload.
5. Verify existing sites still respond.
