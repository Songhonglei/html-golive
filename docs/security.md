# Security scanning

Every `golive publish` runs a rule-based scan before anything goes live.

## Verdicts

Two kinds of finding, and only one of them can be waived.

| finding | examples | effect |
|---|---|---|
| **credential** (strong) | private key header, database DSN, `AKIA…`, `sk-…`, `ghp_…`, bearer token, JWT, `password=` assignment, national ID | **blocks the publish — no flag waives it** |
| **content** (weak) | nouns that legitimately appear in docs: "API key", "token", "salary", "密钥" | warns and publishes; `--skip-content-scan` silences the warning |

A false positive on wording is waivable; a live secret is not. If a
credential is already public or revoked, replace it with a placeholder —
see [Placeholders](#placeholders) below.

`--skip-scan` still works as an alias for `--skip-content-scan` and prints a
deprecation notice. It has no removal date.

The same scan runs on `golive publish`, editor saves, and `golive import`.
Import scans each page and holds back only the offending page: the rest of
the restore proceeds (import is not atomic, so stopping midway is worse),
the registry row for a held-back page is rolled back so it does not become a
site with no content, and the exit code is non-zero.

## Placeholders

Setup documentation must stay publishable. Blocking a guide is how people
learn to publish with the scan waived, and that habit is what lets a real
secret through later. These all publish cleanly:

```
password=***                 API_KEY=<your-key-here>
password=$DB_PASSWORD        token: {{ api_token }}
secret_key = "REPLACE_ME"    API_KEY=sk-REPLACE_ME
password=                    API_KEY=&lt;your-key-here&gt;
```

The exemption requires the placeholder to be the **entire** value. A
placeholder used as a prefix is not a placeholder:

```
password=***RealSecret123     → blocked
API_KEY=REPLACE_MEsk-abc…     → blocked
```

A known credential type prefix (`sk-`, `pk-`, `Bearer `, `Basic `, `token `) may
precede the placeholder, since documentation often keeps the type and
replaces only the secret.

## What a blocked report shows you

A refusal has to be actionable: you need to find the credential in your own
page. So findings keep the parts that identify *which* secret it is, and drop
the parts that make it usable.

For a connection string:

```
mysql://tester:****@db.example.test:3306/app
```

**Kept:** scheme, username, host, port, database path.
**Dropped:** the password.

Everything else — API keys, tokens, assignments, national IDs — keeps a short
recognisable head and nothing more (`sk-abcd****`, `44****34`).

This is a deliberate trade. Blanking the whole match would satisfy "no
sensitive substring in the output" and leave someone with four masked DSNs
and no way to tell which one to go fix.

### If the retained metadata matters to you

The kept parts are not the secret, but in some organisations a hostname,
database name or username does reveal internal topology, a tenant, or a
person's identity. Two things follow:

- **Scan history stores exactly what the console prints** — same redaction
  function, no second policy. If the console shows a host, the database row
  holds that host.
- **CI logs are the case to think about.** Interactive local use is the
  design target; a refusal captured into a shared build log carries the
  retained metadata with it.

If that metadata is itself something to keep in, use
[strict mode](#strict-mode).

### Strict mode

```yaml
security:
  redact_mode: strict     # locator (default) | strict
```

Env override: `GOLIVE_REDACT_MODE`.

Strict withholds the metadata as well, keeping a scheme and a short
fingerprint. The difference shows up in both parts of a finding:

```
locator (default)
  · [database connection string] mysq****
    Context: ...<p>mysql://tester:****@db.example.test:3306/app</p>...

strict
  · [database connection string] mysql://****#c6caf755
    Context: (strict mode: line 3; context withheld)
```

The default keeps the readable form in the context snippet — that is where
the host and database name appear, and where a CI log would pick them up.

The fingerprint is a truncated SHA-256 of the credential — **stable** across
runs and machines, so a repeated refusal is recognisable as the same one, and
**distinct** per credential, so two secrets stay tellable apart in a log
without either being named. It is not reversible and is not a way to check a
value.

What gets fingerprinted is the **secret itself**, not the string it was found
in. For a connection string that means the password, so two DSNs pointing at
different hosts with the same password share one fingerprint. That is the
intended reading — one credential, reused in two places, is one thing to go
rotate — but it does mean strict mode alone will not tell you *which* of the
two endpoints a refusal came from. Use `locator` mode locally when that is
what you need; strict exists for logs that leave the machine.

Context snippets are replaced by a line number. The snippet is a slice of the
page, so it carries the same metadata; masking the credential inside it would
not help.

Two things worth knowing before turning it on:

- **The verdict never changes.** Strict alters what a refusal prints, not what
  gets blocked.
- **A typo is refused, not ignored.** `redact_mode: strictt` raises a config
  error rather than falling back to the default. Every other malformed setting
  degrades to a default with a warning; this one does not, because quietly
  handing someone weaker redaction than they asked for is the failure mode
  worth avoiding.

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

## Scan history

Every scan is recorded, including refusals, so `golive doctor` can tell a
page that was checked from one that never was:

```
scan history   12 scans on record, 9 sites checked (keeping 20 per site)
               2 site(s) have never been scanned
```

A site with no record was published by an older version or restored around
the scanner, and nobody has looked at what is on it.

```yaml
security:
  scan_keep: 20        # records kept per site; 0 keeps everything
```

Env override: `GOLIVE_SCAN_KEEP`.

Records live in the local registry database, whatever the registry backend
is — they are this machine's audit trail, not business data, and nobody
wants them migrated along with their sites. Pruning is **per site**, so a
page published hundreds of times cannot evict the only record another site
has.

**Findings are stored redacted.** Keeping the matched credential would move
the secret out of the page and into a database file that gets backed up.
Only the rule name, category and a masked excerpt are kept; storage reuses
the same masking function as the console output, so the two cannot drift.

A cached verdict is reused only when the page **and** the ruleset are
identical — the cache key is `content_sha256 + ruleset_hash + policy +
scanner_version`. Reusing a verdict because it is "recent" would clear an
edited page, or keep clearing a page after the rule that now catches it was
added.

## Regression corpus

Scanner behaviour is pinned by a corpus of sample pages under
`tests/corpus/`:

```
tests/corpus/
├── README.md
├── must_block/    contains a credential; publishing must be refused
└── must_pass/     contains none; must publish without a BLOCK
```

`tests/test_scanner_corpus.py` walks these directories at run time, so
**adding a case means adding a file** — there is no list in the test to keep
in sync.

### Adding a case

1. Drop an `.html` file into `must_block/` or `must_pass/`, named for what
   it covers (`aws_access_key.html`, `base64_image.html`).
2. Run the corpus:

   ```bash
   python3 -m pytest tests/test_scanner_corpus.py -v
   ```

Every `must_block` sample is tried under **all** waiver flag combinations
(none, `--skip-content-scan`, `--skip-scan`, both) and must be refused by
each; the test also asserts that no long secret-shaped literal from the
sample survives into the report.

### Writing the samples

Assemble the secret from fragments so the repository does not itself carry a
literal credential, and use obviously fake values:

```html
<p>key: sk-<!-- split -->0123456789abcdefghij</p>
```

Never paste a real key, even a revoked one.

### `must_pass` matters as much as `must_block`

A scanner that cries wolf gets routed around: someone reaches for
`--skip-content-scan` by reflex, or stops publishing the page that actually
mattered. Every false positive fixed here is a real credential caught later.
The corpus therefore keeps both halves, and both directions are treated as
regressions.

Current coverage: 22 `must_block` samples (private keys, DSNs across the
supported dialects,
cloud access keys, GitHub/PyPI/Slack/Google tokens, JWTs, bearer tokens,
credential assignments in JS, national ID, placeholder-prefix disguises) and
14 `must_pass` samples (base64 images, URL-encoded text, commit hashes, long
hex ids, years, CSS values, ports, version strings, prose about configuring
keys, and every supported placeholder form).

The corpus lives in the repository, not the wheel — `pyproject.toml` packages
only `golive*`. It is a development asset, run from a checkout or in CI.

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
