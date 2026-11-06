# FrappeOps

Frappe & ERPNext Infrastructure Control Center.

FrappeOps is a **control plane** for managing Frappe/ERPNext infrastructure: servers, benches, sites, apps, domains, nginx, SSL, backups, deployments, monitoring, and AI-assisted operations.

## Status

**0.3.0 — Local MVP** on `frappeops.local`: full Waves A–J control plane (ops, domains, agents/poll, deploy/DR, alerts, AI, bench/SSL tooling). See `docs/RELEASE_0.3.0.md`.

## Important safety rules

- Do **not** install FrappeOps on customer/production ERPNext sites.
- Use a dedicated control site (development: `frappeops.local`).
- Never destroy or modify existing production sites without explicit approval.
- No arbitrary shell from the UI — operations use an allowlisted registry.
- No fake “success” UI for unimplemented features.

## Development control site

```text
Site:  frappeops.local
Bench: /home/frappe/frappe-bench
App:   apps/frappeops
```

Protected existing site on this bench: treat as production-adjacent — do not target it for destructive tests.

## Docs

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [DEVELOPMENT.md](DEVELOPMENT.md)
- [SECURITY.md](SECURITY.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)
- [AGENTS.md](AGENTS.md)
- [CHANGELOG.md](CHANGELOG.md)
- [docs/AGENT.md](docs/AGENT.md)
- [docs/ACCEPTANCE_CHECKLIST.md](docs/ACCEPTANCE_CHECKLIST.md)
- [docs/RELEASE_0.3.0.md](docs/RELEASE_0.3.0.md)
- [docs/SECURITY_HARDENING.md](docs/SECURITY_HARDENING.md)
- [docs/AI.md](docs/AI.md)

Master specification (bench root): `FRAPPEOPS_MASTER_SPEC.md`

## License

MIT
