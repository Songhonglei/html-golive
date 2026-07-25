# html-golive

> **Self-hosted one-command HTML deployment — Vercel-lite for your intranet.**

Turn any HTML file, project folder or zip archive into a shareable URL on
your own machine, NAS, VPS or intranet server.

```bash
pip install html-golive

golive publish report.html --name "Q3 Report" --slug q3
# ✅ Published → http://localhost:8787/q3

golive serve
```

**Zero config to start** — local storage + SQLite + built-in server.
**Grows with you** — swap in Supabase or any S3-compatible backend
(MinIO / Tencent COS / Aliyun OSS / Volcengine TOS) with one yaml file.

---

## Table of contents

- [Why html-golive](#why-html-golive)
- [Quickstart](#quickstart)
- [Features](#features)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [Data layer](#data-layer-give-static-pages-a-database)
- [Security scanning](#security-scanning)
- [Docker](#docker)
- [Roadmap](#roadmap)

> 📖 **Full user manual**: [docs/manual.md](docs/manual.md) — every feature,
> organised by task (publishing, editor, access control, data, security,
> identity, migration, FAQ).

## Why html-golive

- **One command, one URL.** No build step, no server code, no cloud
  account. `golive publish` → share the link.
- **Everything becomes a single file.** Folders and zips are bundled —
  CSS/JS inlined, images compressed and embedded (or uploaded through
  your own image host).
- **Static pages, real data.** Publish a plain HTML file that reads and
  writes a real database via `window.TemplateAPI` /
  `window.SupabaseAPI` — no backend code required.
- **Own your stack.** Runs entirely on your infrastructure. No outbound
  calls at publish/serve time ([details](#network-behavior)).
- **Production habits built in.** Slug collision checks, 10-snapshot
  rollback, credential/PII scanning on every publish, audit log.

## Quickstart

### 1 · Install

```bash
pip install html-golive              # core
pip install 'html-golive[image]'     # + image compression (Pillow)
pip install 'html-golive[s3]'        # + S3-compatible backends (boto3)
```

### 2 · Publish

```bash
golive publish index.html --name Demo --slug demo
golive publish ./my-project/ --slug app      # folder → bundled single HTML
golive publish site.zip                      # zip / tar.gz work too
golive publish page.html --style apple       # apply one of 19 CSS styles
```

### 3 · Serve

```bash
golive serve --port 8787
# → http://<your-host>:8787/demo
```

### Everyday commands

```bash
golive list                                  # all published sites
golive publish new.html --update demo        # overwrite update
golive rollback demo --dry-run               # inspect snapshots, then --yes
golive preview draft.html                    # live preview + style panel
golive clone https://example.com --save-only # snapshot a public page
golive styles                                # list the 19 CSS styles
golive doctor                                # environment health check

# v0.3 — online editing & watermark
golive publish page.html --enable-editor --owner you@example.com
golive maintainer add demo teammate@example.com
golive publish page.html --watermark "CONFIDENTIAL"
```

### Online editing (v0.3)

```bash
export GOLIVE_EDITOR_TOKEN=$(openssl rand -hex 16)
golive publish report.html --slug q3 --enable-editor --owner you@example.com
golive serve
# open http://localhost:8787/q3?editor_token=<token>&editor_user=you@example.com
# click ✏️ → edit text inline → 💾 save (snapshot taken automatically)
```

Saves go through the same security scanner as publishes, are limited to
the site owner + maintainers, and every overwrite is preceded by a
rollback snapshot. With `auth.provider: oidc` the editor accepts the
login session instead of the token+header pair.

## Features

**Publishing & content**
- Single HTML / directory / zip / tar.gz publishing with asset bundling
- 19 built-in CSS beautification styles (`--style`, custom font CDN via
  `GOLIVE_FONT_CDN_BASE`)
- Image compression (`--compress`) and pluggable image upload
  (`GOLIVE_UPLOADER_CMD` command template, or native S3 uploader)
- Website cloning (`golive clone <url>`) with static snapshot mode

**Operations**
- Short slugs with reserved-word and collision checks
- Rollback with 10 snapshots per site
- Built-in static server with JSON API and health endpoint
- Live preview with hot reload and style-switch panel
- `golive doctor` environment diagnostics, audit log

**Data & backends** *(v0.2)*
- `window.TemplateAPI` / `window.SupabaseAPI` injection — static pages
  get a real database with zero backend code
- Storage / registry / data backends: local + SQLite (default),
  Supabase (one project covers all three), S3-compatible object storage
- `golive migrate-check` — port pages from other golive deployments
- Docker Compose deployment (+ optional MinIO profile)

**Editing, identity & watermarking** *(v0.3)*
- In-browser inline editor (`publish --enable-editor`): contenteditable
  text editing with a save API that re-runs the full security pipeline,
  snapshots before every overwrite, and enforces owner/maintainer ACLs
  (`golive maintainer add/remove/list`)
- Page watermarking (`--watermark [text]`): canvas-tiled identity
  watermark — OIDC user, static text, or page meta tag; optional
  view-report webhook; `GOLIVE_WATERMARK_OFF=1` kill switch
- Generic **OIDC login** (`auth.provider: oidc`): Google / Keycloak /
  Authentik / any discovery-document IdP; PKCE + signed session cookies;
  sessions accepted by the management and editor APIs
- Optional **LLM security review** of weak scan hits via any
  OpenAI-compatible endpoint (`security.llm.*`), with a conservative
  degrade path and a `strict_mode` gate

**Safety**
- Credential / PII scanning on every publish (YAML-extensible rules)
- Path-traversal-hardened server and archive extraction
- Token-protected management API (`GOLIVE_TOKEN`)

## Architecture

```
┌────────────── golive core (pure logic) ───────────────────┐
│ bundle / image compress / CSS styles / clone / preview /  │
│ security scanner / slug checker                           │
└──────┬──────────────────┬──────────────────┬──────────────┘
  StorageBackend    RegistryBackend     DataBackend
  site HTML/assets  site metadata       TemplateAPI/SupabaseAPI
       │                  │                  │
  local-fs / s3 /    SQLite / supabase   supabase (PostgREST)
  supabase storage
       │
  AuthProvider: none (default) / token (GOLIVE_TOKEN) / oidc (generic OIDC)
```

All data lives under `GOLIVE_HOME` (default `~/.golive/`):

```
~/.golive/
├── sites/<site_id>/index.html   published content
├── backups/<site_id>/           rollback snapshots (max 10)
├── registry.db                  SQLite registry
├── logs/                        audit log
└── cache/                       style backups etc.
```

## Configuration

Everything works with zero config. Two layers of knobs, **env always
wins over yaml**:

### golive.yaml (backend selection)

Lookup order: `--config <path>` → `$GOLIVE_CONFIG` → `./golive.yaml` →
`$GOLIVE_HOME/golive.yaml`. Full annotated example:
[golive.example.yaml](golive.example.yaml) · backend combinations:
[docs/backends.md](docs/backends.md)

### Environment variables

| Variable | Purpose |
|---|---|
| `GOLIVE_HOME` | data directory (default `~/.golive/`) |
| `GOLIVE_TOKEN` | protect `/api/sites` (Bearer or `X-Golive-Token`) |
| `GOLIVE_EDITOR_TOKEN` | online-editor save token (falls back to `GOLIVE_TOKEN`) |
| `GOLIVE_WATERMARK_TEXT` / `GOLIVE_WATERMARK_OFF` | watermark text / global kill switch |
| `GOLIVE_OIDC_CLIENT_SECRET` / `GOLIVE_COOKIE_SECRET` | OIDC client secret / session-cookie HMAC key |
| `GOLIVE_LLM_BASE_URL` / `GOLIVE_LLM_MODEL` / `GOLIVE_LLM_API_KEY` | LLM security review endpoint |
| `GOLIVE_FONT_CDN_BASE` | swap `fonts.googleapis.com` for your font mirror |
| `GOLIVE_UPLOADER_CMD` | image-upload command template (`mytool up {file}`) |
| `GOLIVE_SUPABASE_URL` / `_ANON_KEY` / `_SERVICE_KEY` | Supabase backends |
| `GOLIVE_S3_AK` / `GOLIVE_S3_SK` | S3-compatible backends |
| `FIRECRAWL_API_KEY` | optional JS-heavy-page fallback for `golive clone` |

### Network behavior

golive makes **no outbound calls** at publish/serve time. Exceptions:
`golive clone <url>` fetches the target page; `golive preview` downloads
a one-time Tailwind cache from `cdn.tailwindcss.com` on first run (fails
silently offline); injected styles reference public font CDNs
(override with `GOLIVE_FONT_CDN_BASE`); your own uploader command and
configured backends.

## Data layer: give static pages a database

Backed by your own Supabase project — no server code:

```bash
golive db init --print-sql              # paste into Supabase SQL editor
golive publish app.html --data-model myapp_v1
```

Your page then simply calls:

```js
// namespaced record store
await TemplateAPI.upsert({ templateName: 'vote:alice', templateContent: {n: 1} });
const { total, list } = await TemplateAPI.listAll();

// or direct table access
const { rows } = await SupabaseAPI.query('feedback', { limit: 50 });
```

API signatures are **stable contracts** — pages built on any golive
deployment run unchanged on yours. Guide with RLS security notes:
[docs/data-layer.md](docs/data-layer.md).

> **Note**: if no data backend is configured, `--data-model` publishes
> still succeed — the page gets a stub API that raises a clear
> "data backend not configured" error at call time (a warning is also
> printed at publish time).

Porting pages from another deployment?
`golive migrate-check page.html` reports anything deployment-specific
([migration guide](docs/migrate-from-intranet.md)).

## Security scanning

Every publish is scanned against built-in rules — API keys, private
keys, database connection strings, PII patterns. Strong hits block the
publish; weak hits warn — and can optionally get a semantic second pass
from any OpenAI-compatible LLM (`security.llm.base_url`; works with
OpenAI / Azure / Ollama / self-hosted gateways). Unconfigured installs
keep pure rule verdicts; `strict_mode: true` refuses to publish without
AI review. Extend with your own YAML rules, or bypass a false positive
with `--skip-scan`. Details: [docs/security.md](docs/security.md)

## Docker

```bash
docker compose up -d golive                 # golive serve on :8787
docker compose --profile minio up -d        # + local S3 stack for images
```

## Roadmap

- ~~**M1 — core**: publish/serve/rollback, styles, clone, preview, scan~~ ✅ v0.1
- ~~**M2 — data layer**: Supabase backend trio, TemplateAPI/SupabaseAPI
  injection, S3 adapters, migrate-check, Docker Compose~~ ✅ v0.2
- ~~**M3 — editing & identity**: inline editor with versioned save API,
  watermarking, OpenAI-compatible LLM security review, generic OIDC~~ ✅ v0.3
- ~~**M4 — docs & polish**: OIDC provider presets, editor image upload,
  persistent cookie secret, full user manual~~ ✅ v0.4
- **M5 — collaboration & scale**: shared session store (redis), multi-user
  editing conflicts UX, group-based ACLs, admin operations portal.

## License

[MIT](LICENSE) © 2026 Songhonglei

---

中文文档请见 [README.zh-CN.md](README.zh-CN.md)。
