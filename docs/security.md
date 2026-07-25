# Security scanning

Every `golive publish` runs a rule-based scan before anything goes live.

## Verdicts

- **strong hit → BLOCK** — definite credential literals (AWS keys, private
  key headers, DB connection strings, `password=` assignments, ...).
  Publish is refused; fix the content or use `--skip-scan` for confirmed
  false positives.
- **weak hit → WARN** — nouns that legitimately appear in docs
  ("API key", "token", "密钥"...). Published with a warning. M3 adds an
  optional LLM second-pass review for these.

## Rule file format

Built-in rules: `golive/security/rules.yaml`. Two sections:

```yaml
keyword_rules:
  - type: credential          # category label
    name: 机密凭证（强特征）    # display name
    strength: strong          # strong | weak
    keywords:
      - api_key
      - "jdbc:"

regex_rules:
  - type: credential
    name: AWS AccessKey
    pattern: '\bAKIA[0-9A-Z]{16}\b'
    strength: strong
```

Keyword matching is word-boundary aware for ASCII terms and uses a
CJK "sticky character" blocklist to suppress compound-word false positives
(e.g. 手机械 does not hit 手机). Base64 / URL-encoded blobs are stripped
before scanning to avoid random-alphabet hits.

## Extending rules

Add your own file with the same schema and reference it in `golive.yaml`:

```yaml
security:
  extra_rules:
    - ~/my-golive-rules.yaml
```

## LLM review (M3)

Weak hits can get a semantic second pass from any **OpenAI-compatible**
Chat Completions endpoint. Strong hits always block — they are never sent
to the LLM.

```yaml
security:
  llm:
    base_url: https://api.openai.com/v1
    api_key_env: GOLIVE_LLM_API_KEY   # env var holding the key
    model: gpt-4o-mini
    timeout: 20
    strict_mode: false
```

Env overrides: `GOLIVE_LLM_BASE_URL`, `GOLIVE_LLM_MODEL`,
`GOLIVE_LLM_API_KEY`.

### Policy matrix

| Situation | Behavior |
|---|---|
| `base_url` unset (default) | AI layer skipped; rule verdicts stand |
| `strict_mode: true` + unset | **publish refused** — you asked for "no AI review, no ship" |
| LLM says `sensitive: true` | hit kept (warn/block per strength) |
| LLM says `sensitive: false` | hit cleared as a false positive |
| LLM timeout / HTTP error / unparseable output | conservative fallback: rule hits kept, warning logged |

### What gets sent

Only the masked hit **contexts** (± 30 chars around each keyword) — never
the full HTML. Contexts are fenced as JSON data and the prompt instructs
the model to ignore any instructions embedded in them (prompt-injection
guard); numbers and secret-looking values are partially masked by the
scanner before they ever reach the LLM.

### base_url compatibility

| Provider | base_url |
|---|---|
| OpenAI | `https://api.openai.com/v1` |
| Azure OpenAI | full deployment URL ending in `/openai/deployments/<name>` (append `api-version` via gateway) — or front it with an OpenAI-compatible proxy |
| Ollama (local) | `http://localhost:11434/v1` (api key can be empty) |
| OneAPI / new-api / self-hosted gateways | your gateway URL ending in `/v1` |
| vLLM / LM Studio | `http://<host>:<port>/v1` |
