# FrappeOps 0.3.0 — Local MVP Release

**Date:** 2026-08-13  
**Control site:** `frappeops.local`  
**Protected site:** `ss.frappe.my` (must remain untouched)

## What’s in 0.3.0

Local control plane covering Waves A–J:

- Ops registry + Operation Job + Audit + protected-site policy
- Site ops, test site create, migrate, app install
- Domain nginx (FrappeOps snippets only)
- Agents: enroll/push + outbound poll + loopback agentd
- Deploy / backup / restore (gated)
- Monitoring alerts + AI plan→approve→execute (local rules, Ollama, OpenAI-compatible)
- Bench doctor / versions / build / gated restart
- SSL inspect + tooling check; Certbot issue path gated

## Compatibility

| Component | Version |
|-----------|---------|
| Frappe | 16.x |
| Bench | 5.x |
| Agent protocol | 0.2.x |
| Control plane | 0.3.0 |

## Upgrade

```bash
cd /home/frappe/frappe-bench
bench --site frappeops.local migrate
bench build --app frappeops
# restart web/workers as usual
```

## Rollback

Restore control-site DB backup taken before migrate. App code rollback via git checkout of `apps/frappeops`.

## Blocked / external dependencies

| Item | Blocker |
|------|---------|
| Live Let's Encrypt issue | Public DNS domain + Settings Allow SSL Issue |
| Cloud OpenAI/Claude | Operator API key + Allow Public AI URLs |
| Multi-server acceptance | Second VM + remote agentd |
| Production sign-off | Dedicated non-shared test host recommended |

## Security baseline (0.3.0)

- No arbitrary shell ops in registry
- Secrets redacted in jobs/audit; agent keys hashed + encrypted Password for outbound
- SSRF guards on agent listen URLs and AI base URLs (loopback/private default)
- High/Critical blocked from AI execute
- Protected site refuses destructive ops

Automated tests: `bench --site frappeops.local run-tests --app frappeops`
