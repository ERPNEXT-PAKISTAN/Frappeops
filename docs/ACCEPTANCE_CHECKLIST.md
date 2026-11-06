# FrappeOps Acceptance Checklist (0.3.0 Local MVP)

Control site: `frappeops.local`  
Protected site: `ss.frappe.my` (must remain untouched by destructive ops)

## Core safety

- [x] FrappeOps installed only on control site
- [x] Protected site blocks clear-cache / migrate / deploy / restore / nginx apply
- [x] No arbitrary shell for operators
- [x] Secrets (passwords, tokens, API keys) not stored plaintext in Job/Audit output
- [x] `frappe-bench.conf` never overwritten by Domain apply
- [x] SSRF guards on agent listen URLs and AI base URLs
- [x] Unit tests for registry / redaction / SSRF / AI plan normalize

## Waves A–J (local)

- [x] Ops registry + Operation Job + Audit
- [x] Site health / backup / maintenance (safe)
- [x] Test site create naming guard (`test-*.local`)
- [x] Domain nginx generate → diff → confirm apply
- [x] Agent enrollment + heartbeat + revoke
- [x] Outbound agent poll + loopback agentd
- [x] Deploy pipeline backup → migrate → health
- [x] Backup retention scan; purge gated
- [x] Ops Alert monitoring + auto-resolve
- [x] AI Task plan → approve → execute (local / Ollama / OpenAI-compatible)
- [x] Bench doctor / versions / build / gated restart
- [x] SSL inspect + tooling check; issue path gated
- [x] API v1 + CLI status/monitor
- [x] Overview agents + domains strips

## Still needs external input

- [x] Certbot installed on host (`certbot` + nginx plugin)
- [x] `ssl.diagnose` proves `ss.frappe.my` DNS ≠ this host (`178.18…` vs `202.163…`)
- [x] Remote-sim second agent (`SRV-0002` / `:18766`) for multi-agent poll demos
- [ ] Live Certbot issue on a **public** domain whose A record = `202.163.76.151`
- [ ] Cloud OpenAI/Claude acceptance with a real API key (paste once → `ai.configure_cloud`)
- [ ] Real second VM (private IP) — remote-sim is loopback only

See `docs/EXTERNAL_INPUTS.md`.

## Manual smoke (operator)

1. Overview → Poll Alerts / Agents / Domains strips  
2. Bench → Doctor / Versions; Build with confirm for `frappeops`  
3. SSL Check → expect honest blockers without public DNS  
4. `bench --site frappeops.local run-tests --app frappeops`  
5. `bench --site frappeops.local frappeops-status`  
6. Confirm `ss.frappe.my` still refuses Deploy Pipeline  
