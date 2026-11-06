# AGENTS.md — Guidance for coding agents (Cursor, Codex, Claude, etc.)

You are working on **FrappeOps**, an infrastructure control plane for Frappe/ERPNext.

## Read first

1. Bench-root `FRAPPEOPS_MASTER_SPEC.md`
2. `FRAPPEOPS_ENVIRONMENT_REPORT.md`
3. `FRAPPEOPS_IMPLEMENTATION_PLAN.md`
4. This app’s `ARCHITECTURE.md`, `DEVELOPMENT.md`, `SECURITY.md`

## Absolute rules

- **Inspect before change.** Do not assume site names, versions, or credentials.
- **Protect existing ERPNext sites** (on this host: `ss.frappe.my`). No drop/uninstall/destructive migrate without explicit user approval.
- **No fake features.** Unimplemented actions must say so.
- **No arbitrary shell** for end users; use operation allowlists.
- **No secrets in Git, logs, or chat dumps.**
- **No `bench update` / `git reset --hard` / `git clean -fd`** unless explicitly approved.
- Prefer the dedicated site `frappeops.local` for all FrappeOps development.

## Implementation order

Follow phases in `FRAPPEOPS_IMPLEMENTATION_PLAN.md`. Do not jump to “production ready” without foundation, discovery, and safe operations.

## When to stop and ask

DNS, SSL, firewall, SSH hardening, production nginx, database restore/drop, site deletion, remote server credentials, AI provider API keys.
