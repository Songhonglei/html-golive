# golive CLI — full reference

Everything `golive --help` exposes, with the flags that matter in
practice. Run `golive <command> --help` for the authoritative list on the
installed version.

Global flags, valid before any subcommand:

| Flag | Meaning |
|---|---|
| `--version` | print the installed version and exit |
| `--config PATH` | use a specific `golive.yaml` |

Config lookup order: `--config` → `$GOLIVE_CONFIG` → `./golive.yaml` →
`$GOLIVE_HOME/golive.yaml` → built-in defaults. Environment variables
always beat the file.

## publish

```bash
golive publish <source> [options]
```

`<source>` is an HTML file, a project directory, or a `.zip` / `.tar.gz`
archive.

| Flag | Effect |
|---|---|
| `--name TEXT` | site name (defaults to the page `<title>`) |
| `--slug TEXT` | short URL: `/report`. Omit and the site is only at `/s/<site_id>` |
| `--update REF` | republish over an existing site (slug or site_id) and snapshot the old content |
| `--entry FILE` | entry HTML for directory / archive sources |
| `--style NAME` | inject a built-in CSS theme (`golive styles`) |
| `--owner EMAIL` | record the site owner |
| `--data-model CODE` | data-layer namespace; comma-separated for several |
| `--enable-editor` | inject the in-browser editor and mark the site editable |
| `--watermark [TEXT]` | inject a page watermark |
| `--compress` | recompress inline images |
| `--skip-scan` | skip the security scan — only on explicit request |
| `--port N` | port used when printing the resulting URL |

Publishing prints `site_id`, `slug` and the URL. Quote them verbatim
back to the user.

## list

```bash
golive list
```

Every registered site with id, slug, name and last update. Run this
before any update or rollback to resolve the right target.

## rollback

```bash
golive rollback <site> [--snapshot TS] [--dry-run] [--yes]
```

`<site>` is a slug or site_id. `--dry-run` lists snapshots without
changing anything — do this first. Without `--snapshot` the newest
snapshot is restored. Snapshots are created by each `publish --update`;
the most recent ones per site are retained.

## serve

```bash
golive serve [--port 8787] [--host 127.0.0.1]
```

Serves every published site plus `/admin`. Defaults to loopback.
`--host 0.0.0.0` publishes to the whole network — pair it with
`GOLIVE_TOKEN` or OIDC. Single-process stdlib server; use a real reverse
proxy for TLS or load.

Routes: `/` index · `/<slug>` · `/s/<site_id>` · `/health` ·
`/admin` · `/api/admin/*` · `/api/data/<table>` (server-proxied data backends: sqlite, postgres).

## preview

```bash
golive preview [file] [--dir DIR] [--entry FILE] [--site REF]
               [--css-style NAME] [--port 18765] [--host 127.0.0.1]
               [--no-open]
```

Local live-reload preview with a style switcher. Nothing is published.

## styles

```bash
golive styles
```

Lists the built-in CSS themes usable with `publish --style`.

## maintainer

```bash
golive maintainer list   <site>
golive maintainer add    <site> <email>
golive maintainer remove <site> <email>
```

Maintainers may edit and roll back a site; they cannot delete or
transfer it.

## admin

```bash
golive admin open [--port 8787]
```

Prints the admin portal URL. The portal itself needs `serve` running.

## data

```bash
golive data list   --model-code CODE [--name PREFIX] [--limit N]
golive data get    --id ID
golive data create --model-code CODE --name NAME [--content JSON] [--desc TEXT]
golive data upsert --model-code CODE --name NAME [--content JSON]
golive data update --id ID [--name NAME] [--content JSON] [--desc TEXT]
golive data delete --id ID
```

`--content` takes inline JSON or `@file.json`. Operates on whichever
data backend is configured (sqlite by default).

## db

```bash
golive db init [--print-sql]
```

With local backends this confirms the SQLite files are ready (tables are
created automatically on first use). `--print-sql` emits the Supabase
schema for the registry and templates tables — PostgREST cannot execute
DDL, so run it in the Supabase SQL editor.

## clone

```bash
golive clone <url> [--name N] [--slug S] [--headless]
              [--analyze-only] [--save-only] [--backend-origin URL]
              [--skip-backend-rewrite]
```

Fetches a public page, localises its assets and publishes it.
`--headless` renders JS-heavy pages first. `--analyze-only` reports what
would happen without publishing.

## migrate-check

```bash
golive migrate-check <file.html>
```

Scans an HTML file for references that will not resolve on this
deployment and reports data-layer call statistics.

## doctor

```bash
golive doctor [--port 8787]
```

Checks `$GOLIVE_HOME` writability, registry readability, site-content
consistency, port availability and optional dependencies. First stop for
any environmental failure.

## skill

```bash
golive skill install [--target DIR] [--from-github] [--force]
golive skill status
golive skill path
```

Installs this skill into an AI agent's skills directory. `install`
auto-detects common locations and asks for `--target` when it cannot.
`status` compares the installed skill version against the running golive
version; `path` prints the bundled source directory.

## Environment variables

| Variable | Purpose |
|---|---|
| `GOLIVE_HOME` | data directory (default `~/.golive/`) |
| `GOLIVE_CONFIG` | explicit config file path |
| `GOLIVE_TOKEN` | static bearer token for `serve` / admin API |
| `GOLIVE_ADMINS` | comma-separated builtin superadmin emails |
| `GOLIVE_SUPABASE_URL` | Supabase project URL |
| `GOLIVE_SUPABASE_ANON_KEY` | anon key (embedded in published pages) |
| `GOLIVE_SUPABASE_SERVICE_KEY` | service key (CLI only) |
| `GOLIVE_EDITOR_TOKEN` | token for the in-browser editor |
| `GOLIVE_S3_*` | S3 storage / uploader credentials |
| `GOLIVE_LLM_BASE_URL` | OpenAI-compatible endpoint for AI review |

## Data directory layout

```
$GOLIVE_HOME/
├── sites/<site_id>/index.html    published content
├── backups/<site_id>/            rollback snapshots
├── registry.db                   sites + managed superadmins
├── data.db                       data layer rows (sqlite backend)
├── audit.log                     admin action trail
├── logs/                         operation logs
└── cache/                        style backups and caches
```
