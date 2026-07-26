# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.4.1] - 2026-07-26

Security hardening + release infrastructure (M1-M4 retrospective fixes).

### Security
- **`GET /api/sites` no longer serves unauthenticated remote callers.**
  With no auth configured, the registry listing (site ids, slugs, names)
  is now only returned to loopback clients; remote callers must present
  a `GOLIVE_TOKEN` bearer token or an OIDC session. Previously any host
  that could reach the port could enumerate all sites.
- **`golive serve` now binds `127.0.0.1` by default** (was `0.0.0.0`),
  matching `golive preview`. Expose deliberately with `--host 0.0.0.0`
  or `server.host` in golive.yaml — the startup banner reminds you to
  pair that with auth.

### Added
- **GitHub Actions CI**: pytest matrix (3.9/3.11/3.12), compileall,
  wheel build with content verification (19 css styles + rules.yaml,
  no pycache), and an install-from-wheel smoke test.

### Changed
- **Published to PyPI**: `pip install html-golive` now works. (Install
  instructions briefly pointed at GitHub while the package was
  unpublished.)

## [0.4.0] - 2026-07-26

Docs, identity presets, and editor polish.

### Added
- **OIDC provider presets** (`golive/backends/auth/presets.py`): set
  `auth.oidc.preset: google | auth0 | okta | azure | keycloak | authentik`
  to auto-fill the issuer template and default scopes — supply only
  `client_id` and the secret env. `auth0`/`okta` take `domain:`, `azure`
  takes `tenant:`. Explicit `auth.oidc.*` fields always override a preset;
  presets contain only public, non-secret values.
- **Editor image upload button**: the online editor toolbar now has a
  🖼 image button that uploads via `POST /api/sites/<slug>/upload` (raw
  body + `X-Filename`), inserting the returned URL at the cursor. When no
  image host is configured (HTTP 501) it gracefully inlines the image as a
  data URL instead.
- **Full user manual** (`docs/manual.md`): a task-oriented guide covering
  all features (publishing, personalisation, styles, cloning, editor,
  access control, data layer, Supabase, doctor, logs, security, sharing,
  backends, identity, migration, FAQ), linked from both READMEs.

### Changed
- **Persistent cookie secret**: when neither `auth.oidc.cookie_secret` nor
  `GOLIVE_COOKIE_SECRET` is set, the OIDC session-signing key is now
  generated once and persisted to `GOLIVE_HOME/.cookie_secret` (mode 0600)
  so sessions survive a restart. Falls back to an ephemeral key with a
  warning only if the home dir is unwritable. (Closes M3 WARN #1.)

## [0.3.0] - 2026-07-25

M3 "editing & identity" milestone.

### Added
- **Online inline editor** (`golive/inject/editor.py` +
  `golive/server/editor_api.py`): per-site opt-in via
  `golive publish --enable-editor`. Floating ✏️ button → contenteditable
  text editing → save through `PUT /api/sites/<slug>/content` with
  Bearer editor token + `X-Editor-User` (URL params stashed in
  sessionStorage; OIDC sessions accepted too). Unsaved-changes guard,
  status toasts, auto-reload after save.
  - Server side: constant-time token compare, per-site `editable` gate,
    **owner/maintainer ACL**, 10 MB body limit, `text/html` content type
    required, snapshot before every overwrite (rollback covers
    conflicts), audit-log entry per save.
  - **The save channel re-runs the full publish security pipeline**
    (code-safety checker + rule/AI scanner) — editing can never bypass
    the scan.
  - Registry schema: `sites.editable` BOOLEAN + `sites.maintainers`
    JSON (SQLite migrates in place; Supabase DDL includes upgrade
    hints). New CLI: `golive maintainer add|remove|list <site> [email]`.
  - Shared-token mode (no owner/maintainer set) triggers an explicit
    warning at `--enable-editor` time.
- **Watermark layer** (`golive/inject/watermark.py`): canvas-tiled
  diagonal identity watermark. Identity sources in priority order:
  OIDC current user (email prefix only — never the full address),
  static text (`watermark.text` / `GOLIVE_WATERMARK_TEXT` /
  `--watermark <text>`), or `<meta name="golive-watermark">`.
  Inline JS by default; `watermark.cdn_url` switches to your own CDN.
  Style knobs: opacity / font_size / rotation / color. Optional
  `watermark.report_webhook` (POST `{slug,user,ua,ts}`) — no telemetry
  by default. `GOLIVE_WATERMARK_OFF=1` kill switch (also strips
  previously injected layers on republish).
- **LLM security review** (`golive/security/ai_review.py`): weak scan
  hits get an optional semantic second pass through any
  OpenAI-compatible Chat Completions endpoint
  (`security.llm.base_url/api_key_env/model/timeout`). Policies:
  unconfigured → skip (rule verdicts stand); `strict_mode: true` +
  unconfigured → publish refused; LLM `sensitive:false` → hit cleared;
  `sensitive:true` → kept; timeout/error/junk → conservative keep.
  Only masked hit contexts are sent (never whole HTML), fenced as JSON
  with a prompt-injection guard. Strong hits always block without an
  LLM call. Compatible with OpenAI / Azure / Ollama / OneAPI / vLLM.
- **Generic OIDC AuthProvider** (`golive/backends/auth/oauth.py`):
  `auth.provider: oidc` with discovery-document auto-configuration.
  Authorization-code flow with **PKCE (S256)** and single-use,
  TTL-bound `state`; userinfo endpoint (id_token claims fallback);
  HMAC-signed session-id cookies (HttpOnly, SameSite=Lax, Secure on
  https or `force_secure_cookie`); in-memory session store with TTL.
  New server routes: `/auth/login`, `/auth/callback`, `/auth/logout`
  (with optional IdP end_session redirect), `/auth/me`. `/api/sites`
  and the editor API accept sessions alongside Bearer tokens.
  Example configs for Google / Keycloak / Dex-bridged GitHub in
  `golive.example.yaml`.
- Shared XSS escaping util `golive/inject/_escape.py` — template_api /
  supabase_api / editor / watermark all import the same
  `json_for_script` / `safe_comment` (one fix, four injectors).
- 68 new tests (129 total): editor ACL + HTTP e2e, watermark identity
  sources & kill switch, mock-LLM policy branches, fake-IdP OAuth flow
  with state/PKCE/cookie tampering, M2 WARN regression tests.

### Fixed
- S3 storage error handling now uses botocore's official
  `ClientError.response['Error']['Code']` (NoSuchKey / 404 / NotFound /
  NoSuchBucket → `FileNotFoundError`, AccessDenied →
  `PermissionError`) instead of substring-matching `str(e)` — an error
  *message* containing "404" no longer masks a real failure.
- Supabase Storage snapshot pruning is now guarded by an advisory
  lockfile (`<site_id>/.prune.lock`, pid+ts payload, 60 s TTL);
  concurrent publishers skip the prune instead of racing on deletes.

## [0.2.0] - 2026-07-25

M2 "data layer" milestone.

### Added
- **Config loader** (`golive/config.py`): `golive.yaml` is now fully
  effective. Lookup order `--config` → `$GOLIVE_CONFIG` → `./golive.yaml`
  → `$GOLIVE_HOME/golive.yaml`; missing file = zero-config defaults;
  env vars always override yaml (12-factor). Secrets stay in env —
  yaml stores `*_env` variable names.
- **Supabase backends** — one Supabase project can host all three layers:
  - registry: `golive_sites` table via PostgREST
    (`golive/backends/registry/supabase_store.py`)
  - storage: site HTML + snapshots in a Storage bucket with a 60 s
    read cache (`golive/backends/storage/supabase_store.py`)
  - data: `golive_templates` table + Python-side `TemplateStore`
    (`golive/backends/data/supabase.py`)
  - shared minimal PostgREST client (`golive/backends/postgrest.py`)
- **S3-compatible backends** (optional extra `pip install
  'html-golive[s3]'`): site storage (`backends/storage/s3.py`) and
  native image uploader with content-hash keys
  (`backends/images/s3.py`). Works with MinIO / COS / OSS / TOS / AWS.
- **JS data-layer injection** (`golive/inject/`): publish now detects
  `TemplateAPI` / `SupabaseAPI` usage and injects
  `window.TemplateAPI` / `window.SupabaseAPI` with signatures
  compatible with the original deployment contract (list / listAll /
  get / create / update / delete / sort / upsert; init / getUser /
  isReady / onReady / logout / query / insert / update / delete).
  Multi-modelCode support, placeholder hard-block, ready events,
  `{total, list}` / `{rows, count}` envelopes preserved. Without a
  configured backend a stub is injected (clear console errors, publish
  never blocked). New publish flag `--data-model`.
- **`golive migrate-check <file>`**: scans HTML for intranet-specific
  references (hard-coded internal hosts, leftover data-layer script
  blocks, data API call statistics) with file:line + advice report.
- **`golive db init --print-sql`**: prints `golive_sites` +
  `golive_templates` schemas with example RLS policies.
- **`golive data <list|get|create|update|delete|upsert>`**: server-side
  CLI twin of TemplateAPI.
- **Docker**: real `Dockerfile` + `docker-compose.yml` (golive serve +
  optional `--profile minio` local S3 stack with bucket bootstrap).
- Backend factory (`golive/backends/factory.py`) — CLI/server pick
  storage/registry/data implementations from config.
- Docs: `docs/data-layer.md` (API reference + examples + RLS warnings),
  `docs/migrate-from-intranet.md`, expanded `docs/backends.md` with
  three worked backend combos; bilingual README updates.
- Tests: config priority suite, in-process fake PostgREST server with
  registry/data CRUD round-trips, injection signature-parity assertions
  (method lists hard-coded from the upstream contract), migrate-check
  fixtures built from fragments at runtime.

### Changed
- `get_uploader()` selection order: env `GOLIVE_UPLOADER_CMD` → yaml
  `uploader.command` → yaml `uploader.s3.bucket` → none (base64).
- `golive.example.yaml` rewritten as a fully working annotated config.

## [0.1.1] - 2026-07-25

### Added
- 8 more built-in CSS styles — newspaper, bloomberg, ink, steampunk,
  palace, cyberpunk, xhs, xhs-fun — bringing the total to 19. Web fonts
  are loaded from Google Fonts (CSS2 API).
- `GOLIVE_FONT_CDN_BASE` env / `style.font_cdn_base` config: swap the
  `fonts.googleapis.com` prefix for a custom font mirror at injection
  time (e.g. `fonts.loli.net` or a self-hosted service).
- `golive preview --host` flag; preview now binds `127.0.0.1` by
  default (use `--host 0.0.0.0` for remote/container environments).
- README "Network behavior" section documenting every outbound call,
  plus the optional `FIRECRAWL_API_KEY` fallback for `golive clone`.
- Custom image uploader: `GOLIVE_UPLOADER_CMD` env /
  `uploader.command` config runs any CLI (`mytool upload {file}`) to
  upload bundled images and reference the returned URL; failures fall
  back to base64 inlining so publishes never break. Native S3 uploader
  reserved for M2.

### Fixed
- `from __future__ import annotations` added to modules using PEP 604
  unions, restoring the documented Python 3.9 compatibility.
- tar.gz extraction now guards against path-traversal members
  (`filter="data"` on Python ≥ 3.12, manual check on older versions).
- Preview panel style labels are now sourced from the canonical
  `STYLE_MAP` (new styles show up automatically).

## [0.1.0] - 2026-07-25

First public release — "M1 core": zero-config single-machine deployment.

### Added
- `golive publish <file|dir|zip>` — publish a single HTML file, a project
  directory (bundled into one HTML with all assets inlined) or a zip/tar.gz
  archive.
- Local-fs storage backend (`$GOLIVE_HOME/sites/`) with automatic snapshots
  (up to 10 per site) and `golive rollback` (dry-run + `--yes`).
- SQLite registry backend (`registry.db`): site id (uuid4 hex), name, unique
  slug, timestamps, owner, notes.
- Built-in HTTP server `golive serve`: `GET /<slug>`, `GET /s/<site_id>`,
  `GET /api/sites` (token-protected via `GOLIVE_TOKEN`), `GET /health`,
  simple site index at `/`.
- Short-slug validation: format check, built-in reserved words (variant-proof
  normalization) and registry collision check.
- Rule-based security scanner with built-in `rules.yaml` (credentials,
  private keys, connection strings, PII); strong hits block publish,
  `--skip-scan` bypass, user-extensible rule files.
- 11 built-in CSS beautification styles (`--style`, `golive styles`).
- Base64 image compression (`--compress`, optional Pillow extra).
- Website cloning `golive clone <url>`: URL classification, fetching with
  resource inlining, migration analysis, font-mirror patching,
  sensitive-config scrubbing, optional headless-Chrome rendering.
- Live preview `golive preview` with hot reload and style-switch panel.
- `golive doctor` environment health check.
- AuthProvider interface with `none` (default) and static-token providers.

### Notes
- Data layer (TemplateAPI/SupabaseAPI), S3 storage, Docker Compose land in M2.
- In-browser editor, watermarking, LLM security review and OAuth land in M3.
