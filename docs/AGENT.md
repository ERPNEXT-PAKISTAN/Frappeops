# FrappeOps Agent (Wave D + H)

Remote agents enroll against the control plane (`frappeops.local`) with a one-time token, then authenticate with an API key.

Two sync modes:

1. **Push** — agent → control plane (`heartbeat` / `execute` guest APIs)
2. **Pull** — control plane → agent listen URL (outbound poll, SSRF-restricted)

## Operator (Desk)

1. Overview → **Install Local Agent** (this host), or **Create Agent Enrollment Token** for a Server.
2. Copy the token / API key when shown (stored as SHA-256 hash + encrypted Password for outbound poll).
3. Overview → **Start Agent Listener** (loopback `127.0.0.1:18765`) for outbound poll on this host.
4. Commands → **Poll Agent** / **Agent Heartbeat** / **Discover via Agent**.
5. **Revoke Agent** to invalidate credentials immediately (clears encrypted key + disables poll).

## Agent → Control Plane API (push)

All guest endpoints authenticate via token or `api_key` (form field or `Authorization: Bearer <key>`).

| Method | Purpose |
|--------|---------|
| `frappeops.api.agent.enroll` | Exchange enrollment token → API key (once) |
| `frappeops.api.agent.heartbeat` | Push host facts + health |
| `frappeops.api.agent.execute` | Allowlisted commands only |

### Scoped commands (push)

`discover`, `health`, `list_sites`, `backup_site`, `heartbeat`

## Control Plane → Agent (pull)

Standalone listener: `apps/frappeops/agent/frappeops_agentd.py`

| Endpoint | Purpose |
|----------|---------|
| `GET /v1/ping` | Liveness (Bearer auth) |
| `POST /v1/execute` | Allowlisted: `ping`, `health`, `discover`, `list_sites`, `heartbeat` |

Config under `config/frappeops-agent/<AGT>.json` (mode `0600`, contains API key — never commit).

### SSRF guards

- Only `http` / `https`
- No embedded credentials, query, or fragment
- Host must resolve to **loopback or private** IPs unless Settings → **Allow Public Agent URLs**
- Link-local / `169.254.*` blocked
- No redirects followed
- Scheduler: `frappeops.tasks.agent_outbound_poll` every 5 minutes for `poll_enabled` agents

### Example remote agentd

```bash
# On the remote host after enroll — write config with api_key, then:
python apps/frappeops/agent/frappeops_agentd.py --config /path/agent.json
# Set FRAPPEOPS_AGENT_ALLOW_NON_LOOPBACK=1 only when binding a private LAN IP intentionally.
```

Then set Server Agent **Listen URL** to `http://<private-ip>:18765` and enable **Poll Enabled**.

## Safety

- Tokens and API keys are never stored in plaintext (hash + Frappe Password encryption).
- Protected production sites are not enrolled for nginx/domain apply via Wave C rules.
- Local listener defaults to loopback bind only.
- `backup_site` is intentionally **not** exposed on the pull listener (push path only / control-plane ops).
