# FrappeOps AI (Wave F + I)

AI Tasks never execute blindly. Flow is always:

```text
Create → Plan → Submit → Approve → Execute (confirm)
```

Only **allowlisted Low/Medium** registry actions can appear in a plan. High/Critical are stripped. Protected sites stay blocked for mutating ops.

## Planners

| Provider | When used |
|----------|-----------|
| **Local Planner** | Default when AI Features off, or `use_local=1` |
| **Ollama Local** | Native Ollama `/api/chat` on loopback |
| **OpenAI Compatible (Ollama)** | OpenAI client against local `http://127.0.0.1:11434/v1` |
| **OpenAI / Claude / …** | OpenAI-compatible `/v1/chat/completions` — needs **API Key** + **Allow Public AI URLs** when not loopback |

Cloud keys are stored only in the encrypted **API Key** Password field.

## Ollama (local)

1. Ensure `ollama serve` is running (`http://127.0.0.1:11434`).
2. Settings → **Enable AI Features**, Default AI Provider = **Ollama Local**.
3. Commands → **Test AI Provider** (lists models).
4. Create AI Task → Plan (uses model) → Submit → Approve → Execute.

Base URL is **loopback-only** unless **Allow Public AI URLs** is on.

## Safety

- No arbitrary shell from AI plans
- Secrets stripped from step params
- Human approval required before execute
- Model output is schema-validated against the ops registry
