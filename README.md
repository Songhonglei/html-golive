# html-golive

> **Self-hosted one-command HTML deployment — Vercel-lite for your intranet.**

Turn any HTML file, project folder or zip archive into a shareable URL on
your own machine, NAS, VPS or intranet server. Zero config to start: local
storage + SQLite registry + built-in HTTP server.

```bash
pip install html-golive

golive publish report.html --name "Q3 Report" --slug q3
# ✅ Published → http://localhost:8787/q3

golive serve            # start the built-in server
```

## Features

| Feature | Status |
|---|---|
| Publish single HTML / directory / zip | ✅ v0.1 |
| Asset bundling (CSS/JS/images inlined into one file) | ✅ v0.1 |
| Base64 image compression (`--compress`, Pillow) | ✅ v0.1 |
| 11 built-in CSS beautification styles (`--style`) | ✅ v0.1 |
| Short slugs with reserved-word & collision checks | ✅ v0.1 |
| Rollback (10 snapshots per site) | ✅ v0.1 |
| Security scan (credentials / PII rules, YAML-extensible) | ✅ v0.1 |
| Website cloning (`golive clone <url>`, headless option) | ✅ v0.1 |
| Live preview with style-switch panel (`golive preview`) | ✅ v0.1 |
| Built-in static server + JSON API (`golive serve`) | ✅ v0.1 |
| Health check (`golive doctor`) | ✅ v0.1 |
| Data layer: Supabase/PostgREST backed `window.TemplateAPI` / `window.SupabaseAPI` | 🚧 M2 |
| S3-compatible storage backend (MinIO/COS/OSS/TOS) | 🚧 M2 |
| Docker Compose deployment | 🚧 M2 |
| In-browser inline editor with save API | 🚧 M3 |
| Watermark & optional LLM security review | 🚧 M3 |
| Token / OAuth auth providers | 🚧 M3 (token basics already in v0.1 serve mode) |

## Quickstart

```bash
# 1. install
pip install html-golive          # add [image] extra for compression:
                                 # pip install 'html-golive[image]'

# 2. publish anything
golive publish index.html --name Demo --slug demo
golive publish ./my-project/ --slug app      # folder → bundled single HTML
golive publish site.zip                      # zip/tar.gz works too

# 3. serve
golive serve --port 8787
# → http://<your-host>:8787/demo

# manage
golive list
golive publish new.html --update demo        # overwrite update
golive rollback demo --dry-run               # inspect snapshots
golive rollback demo --yes                   # restore latest snapshot
golive clone https://example.com --save-only # clone a public page
golive preview draft.html                    # live preview w/ hot reload
golive styles                                # list CSS styles
golive doctor                                # health check
```

## Architecture

```
┌────────────── golive core (pure logic) ───────────────────┐
│ bundle / image compress / CSS styles / clone / preview /  │
│ security scanner / slug checker                           │
└──────┬──────────────────┬──────────────────┬──────────────┘
  StorageBackend    RegistryBackend     DataBackend (M2)
  site HTML/assets  site metadata       TemplateAPI/SupabaseAPI
       │                  │                  │
  local-fs (v0.1)    SQLite (v0.1)      supabase (M2)
  s3 (M2)            postgres/supabase (M2)
       │
  AuthProvider: none (default) / token (GOLIVE_TOKEN) / oauth (M3)
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

Everything works with zero config. Optional knobs:

- `GOLIVE_HOME` — data directory (default `~/.golive/`)
- `GOLIVE_TOKEN` — when set, `/api/sites` requires
  `Authorization: Bearer <token>` (or `X-Golive-Token`)
- `golive.yaml` — backend selection & rule extensions, see
  [golive.example.yaml](golive.example.yaml) (most fields land in M2)

## Security scanning

Every publish is scanned against built-in rules (API keys, private keys,
database connection strings, PII patterns). Strong hits block the publish;
weak hits warn. Extend rules with your own YAML file, or bypass a false
positive with `--skip-scan`.

## Roadmap

- **M2 — data layer**: Supabase backend trio (storage / registry / PostgREST
  data API with stable `window.TemplateAPI` / `window.SupabaseAPI` signatures),
  S3 storage adapter, Docker Compose, image uploader backends.
- **M3 — editing & beyond**: in-browser inline editor with versioned save API,
  watermarking, optional OpenAI-compatible LLM security review, OAuth.

## License

[MIT](LICENSE) © 2026 Songhonglei

---

中文文档请见 [README.zh-CN.md](README.zh-CN.md)。
