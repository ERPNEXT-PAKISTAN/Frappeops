# App Marketplace

Curated **App Catalog Item** rows + `bench get-app` over HTTPS only.

## Operator flow

1. Overview → **Seed** (or Commands → Seed App Marketplace)
2. Click a catalog card → confirm → `app.get` clones into `apps/`
3. Commands → **Install App** on a non-protected site (`app.install`)

Custom GitHub/GitLab:

```bash
bench --site frappeops.local execute frappeops.services.operations.runner.run_action \
  --kwargs "{'action_key':'app.get','target_type':'bench','params':{'git_url':'https://github.com/frappe/hrms','branch':'version-16','confirm':1}}"
```

## Safety

- HTTPS git URLs only (no embedded credentials, no shell metacharacters)
- Protected sites still block `app.install`
- get-app does not run arbitrary repo install scripts beyond bench’s own flow
