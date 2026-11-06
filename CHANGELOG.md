# Changelog

## 0.4.1 — 2026-08-13

### UX

- Easy Control pages: **Overview**, **Site Control**, **Server Control**, **Apps & Install**
- Overview tiles open control pages (not raw DocTypes); site/server cards do the same
- Guided **Install an App** wizard: pick site → ready-on-bench / marketplace → one-click install
- Workspace **Easy Control** card; app icon opens Overview

## 0.4.0 — 2026-08-13

### Added

- **Offsite backups** — Backup Destination (S3 / AWS / Google Drive / Dropbox via rclone / Local), `backup.upload_offsite`, `backup.test_destination`, Settings auto-upload + checksum on local backup
- **Remote VPS status** — `server.register_vps`, `server.status`, `agent.install_script`; richer agent facts; remote `server.health` uses agent (not control-plane disk)
- **App marketplace** — App Catalog Item + seed catalog; `app.get` / `app.list_catalog` / `app.seed_catalog` (HTTPS get-app only)
- Overview: Register VPS, Marketplace strip, Full Status / Enroll / Install Script
- Docs: `docs/BACKUPS_OFFSITE.md`, `docs/MARKETPLACE.md`, `docs/VPS.md`

## 0.3.1 — 2026-08-13

### Added

- `ssl.diagnose` — DNS A vs host public IP + read-only remote cert peek
- Certbot issue preflight refuses when DNS does not point here
- `agent.install_remote_sim` — second loopback agent on `:18766` for multi-agent demos
- `ai.configure_cloud` — encrypted cloud API key setup (blocked without key)
- Docs: `docs/EXTERNAL_INPUTS.md`

## 0.3.0 — 2026-08-13

### Local MVP release

- Waves A–J packaged as a local control-plane MVP on `frappeops.local`
- Security hardening docs + unit tests (registry, redaction, SSRF, AI plan normalize)
- Bench **Versions** + **Build Assets** (confirm-gated)
- Overview: Agents strip, Domains/SSL strip, SSL Check + Poll Agent actions
- `ssl.check_tooling` readiness report (honest blockers)
- Release notes: `docs/RELEASE_0.3.0.md`

### Still external

- Live Certbot for public DNS domains
- Cloud AI with operator API keys
- Second-VM remote agent acceptance

## 0.2.3 — 2026-08-13

### Added

- OpenAI-compatible planner (`/v1/chat/completions`, `/v1/models`)
- AI Provider encrypted **API Key** field
- Seeded **OpenAI Compatible (Ollama)** provider for local `/v1` proof
- Remote non-loopback endpoints require API key + Allow Public AI URLs

## 0.2.2 — 2026-08-13

### Added

- **Ollama Local** AI Provider planner (loopback `11434`, JSON plan schema)
- Settings: Enable AI Features, Default AI Provider, Allow Public AI URLs
- `ai.test_provider` op; plan falls back to local rules when AI off
- Strict allowlist validation of model steps (Low/Medium only)
- Docs: `docs/AI.md`

## 0.2.1 — 2026-08-13

### Added

- Outbound **agent poll** (control plane → agent listen URL)
- Standalone loopback **agentd** (`agent/frappeops_agentd.py`) + Start/Stop Local Listener ops
- Server Agent: `listen_url`, `poll_enabled`, `last_poll_*`, encrypted `api_key_secret`
- SSRF guards on listen URLs (loopback/private default; Settings `allow_public_agent_urls`)
- Scheduler `agent_outbound_poll` every 5 minutes

## 0.2.0 — 2026-08-13

### Added

- **Bench Doctor** (`bench.doctor`) — real `bench doctor` via Operation Job
- **Bench Restart** (`bench.restart`) — gated: Settings `allow_bench_restart` + confirm + typed `RESTART`; dry-run by default
- **SSL Inspect** (`ssl.inspect`) — scan `/etc/letsencrypt/live`, sync **SSL Certificate** records
- **SSL Issue** (`ssl.issue`) — Certbot path with Settings gate + typed `ISSUE`; defaults to dry-run; blocked for `.local` / protected sites
- Settings: Allow Bench Restart, Allow SSL Issue (both default off)
- Monitoring: treat Settings threshold `0` as unset (fixes false Disk/Memory Critical alerts)

## 0.1.0 — 2026-08-13

### Added

- Control plane waves A–F on dedicated site `frappeops.local`
- Ops registry, Operation Job + Audit, protected-site policy
- Site ops, domains, agents, deploy, backups, alerts, AI local planner, API v1, CLI

### Safety

- Never installs on / destroys `ss.frappe.my`
- No arbitrary shell; secrets hashed/redacted; no silent backup deletion

## 0.0.1 — Foundation

- Initial scaffolding, DocTypes, RBAC, discovery import
