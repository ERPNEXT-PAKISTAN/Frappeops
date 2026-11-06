# Remote VPS (Contabo / Hetzner / …)

## Connect a VPS for full status

1. FrappeOps Settings → enable **Enable Remote Agents** (and **Allow Public Agent URLs** if the agent listen URL is a public IP).
2. Overview → **Register VPS** (name, public IP, provider) — creates Server + enrollment token + install script.
3. On the VPS: ensure a Frappe bench exists (or copy `frappeops_agentd.py`), run the install script so the agent can reach the control plane URL.
4. Set Server Agent **Listen URL** to `http://VPS_IP:18765`, enable **Poll**.
5. Overview → **Full Status** / **Health** on that server.

Control plane must be reachable from the VPS (public `ops.…`, VPN, or Tailscale). Office NAT without port-forward cannot be the public control URL.

## Status shown

- Agent online/offline, last heartbeat / poll
- Disk / RAM / CPU / load / hostname / OS / cores
- Site & app lists from agent facts
- Inventory Site/Bench rows when imported

There is no Contabo billing/power API integration yet — inventory + agent facts only.
