# FrappeOps Architecture

## Control plane

FrappeOps runs as a Frappe app on a **dedicated site**. It does not replace ERPNext; it manages infrastructure that may host ERPNext.

```text
FrappeOps UI / API / CLI
          │
   Operation Engine (allowlist, RBAC, audit)
          │
   Agent layer (local adapter → remote agent)
          │
   Servers → Benches → Sites → Apps / Domains / Services
```

## Package layout

```text
frappeops/
  api/           Whitelisted HTTP/API methods
  core/          Permissions, redaction, constants
  services/      Domain logic (servers, sites, nginx, …)
  doctype/       Frappe DocTypes
  utils/         Shared helpers
```

Business logic lives in `services/`, not only in DocType controllers.

## Multi-tenancy model

```text
Organization → Server → Bench → Site → Domain / Apps / Backups
```

One server may host many benches; one bench may host many sites and versions.

## Operations

Every mutating action becomes an **Operation Job** with status, logs, risk level, and audit trail. Long work runs asynchronously.

## Agents

- **Local adapter (near-term):** discover and operate on the control-plane host safely.
- **Remote agent (later):** TLS + revocable credentials, heartbeat, scoped execution.

## Version strategy

Frappe/ERPNext versions are **registry data** (profiles + compatibility rules), not hard-coded product assumptions.
