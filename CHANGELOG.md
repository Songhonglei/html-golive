# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
