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

`security.llm` in `golive.yaml` will let you point weak-hit review at any
OpenAI-compatible endpoint. Unconfigured installs keep pure rule verdicts.
