# External inputs required (honest blockers)

This host public IP: **`202.163.76.151`**  
`ss.frappe.my` DNS currently: **`178.18.246.67`** (different host — LE issue on this machine will fail)  
`:443` on this host: **not listening**  
Protected site: **`ss.frappe.my`** (FrappeOps will not issue/manage SSL for it)

## 1) Live Let's Encrypt

Provide a hostname whose **A record = 202.163.76.151**, then:

1. Register it as a Domain on a **non-protected** site (e.g. `frappeops.local` or `test-*.local`)
2. Settings → enable **Allow SSL Issue**
3. Commands → Diagnose Domain SSL/DNS → confirm `dns_points_to_this_host`
4. Issue SSL with confirm + typed `ISSUE` (dry-run first)

Example once DNS is ready:

```bash
bench --site frappeops.local execute frappeops.services.operations.runner.run_action \
  --kwargs "{'action_key':'ssl.diagnose','target_type':'domain','target_name':'YOUR-DOMAIN','params':{}}"
```

## 2) Cloud AI

Provide an API key (OpenAI or OpenAI-compatible). It is stored encrypted; never commit it.

```bash
bench --site frappeops.local execute frappeops.services.ai.cloud_setup.configure_cloud_provider \
  --kwargs "{'api_key':'sk-...','api_base_url':'https://api.openai.com/v1','default_model':'gpt-4o-mini'}"
```

Or paste the key in chat and ask to configure (do not put keys in git).

## 3) Real second VM

Provide:

- Private IP (or VPN IP) reachable from this host
- Ability to run `frappeops_agentd.py` there

Until then, use **Install Remote-Sim Agent** (loopback `:18766`) for multi-agent poll demos only.
