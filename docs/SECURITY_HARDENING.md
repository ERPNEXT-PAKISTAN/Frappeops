# FrappeOps Security Hardening (0.3.0)

## Controls implemented

| Control | Status |
|---------|--------|
| Allowlisted ops only | Yes — `services/operations/registry.py` |
| No fake success for unimplemented ops | Yes — `planned` / honest errors |
| Secret redaction | Yes — `core/redaction.py` + job output scrubbing |
| Protected site policy | Yes — runner + registry flags |
| Agent credentials | SHA-256 hash + encrypted Password for outbound |
| Agent SSRF | Loopback/private listen URLs; no redirects |
| AI SSRF | Loopback AI URLs by default; public gated |
| AI plan schema | Allowlist Low/Medium only; strip secret params |
| Typed confirms | RESTART / ISSUE / PURGE / site-name restores |
| Rate limits | Agent guest APIs |

## Test coverage

- `tests/test_redaction.py`
- `tests/test_registry.py`
- `tests/test_ssrf_guards.py`
- `tests/test_ai_plan_normalize.py`

## Explicit non-goals (still out of scope)

- Arbitrary remote shell
- Auto `bench update` / git reset
- Blind overwrite of `frappe-bench.conf`
- Silent backup deletion
