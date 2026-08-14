# html-golive User Manual

A complete guide to html-golive, organised by task. New here? Start with
the [Quickstart](quickstart.md), then come back for the details.

> Every feature below runs on **your own infrastructure** — nothing is
> sent anywhere unless you configure a remote backend. See
> [Network behavior](../README.md#network-behavior).

## Contents

1. [Getting started](#1-getting-started)
2. [Publishing: preview, publish, update, rollback, backup](#2-publishing)
3. [Personalisation: title, favicon, short slug](#3-personalisation)
4. [Site enhancement: 19 CSS styles & asset care](#4-site-enhancement)
5. [Cloning another site](#5-cloning-another-site)
6. [Online editor](#6-online-editor)
7. [Access control: owners & maintainers](#7-access-control)
8. [Built-in data storage (TemplateAPI)](#8-built-in-data-storage)
9. [Using Supabase](#9-using-supabase)
10. [Doctor: the one command to verify everything](#10-doctor)
11. [Running as a background service](#11-running-as-a-background-service)
12. [Logs & audit](#12-logs--audit)
13. [Security: scanning, blocking, watermark, LLM review](#13-security)
14. [Sharing: public mirror & Docker](#14-sharing)
15. [Backends: storage / registry / images](#15-backends)
16. [Identity & login (OIDC)](#16-identity--login)
17. [Migrating pages from another deployment](#17-migrating-pages)
18. [Admin portal](#18-admin-portal)
19. [AI agent skill](#19-ai-agent-skill)
20. [FAQ](#20-faq)

---

## 1. Getting started

```bash
pip install html-golive
golive publish index.html --slug hello
golive serve                       # → http://localhost:8787/hello
```

`golive doctor` verifies your environment. Data lives under `GOLIVE_HOME`
(default `~/.golive/`). Full walkthrough: [quickstart.md](quickstart.md).

## 2. Publishing

| Task | Command |
|---|---|
| Preview locally (hot reload) | `golive preview draft.html` |
| Publish a file / folder / zip | `golive publish x.html --slug foo` |
| Update an existing site | `golive publish new.html --update foo` |
| Inspect rollback snapshots | `golive rollback foo --dry-run` |
| Roll back to latest snapshot | `golive rollback foo --yes` |
| List all sites | `golive list` |

Each update keeps up to **10 snapshots** per site; rollback restores the
most recent. Folders and archives are bundled into a single self-contained
HTML file (CSS/JS inlined, images compressed or uploaded).

## 3. Personalisation

- `--name "My Report"` sets the site title in the registry.
- `--slug q3` gives a short, human URL (`/q3`); reserved words and
  collisions are rejected.
- Favicon / meta come from your HTML `<head>` — golive preserves them.

## 4. Site enhancement

19 built-in CSS styles beautify a bare HTML page:

```bash
golive styles                        # list them
golive publish page.html --style newspaper
```

Fonts load from public CDNs by default; point `GOLIVE_FONT_CDN_BASE` at
your own mirror to self-host. golive also bundles and de-duplicates assets
so a multi-file project ships as one file.

## 5. Cloning another site

```bash
golive clone https://example.com --save-only     # snapshot to a file
golive clone https://example.com --slug mirror   # snapshot + publish
```

Use for archiving a public page or seeding a template. Heavy-JS pages can
fall back to a rendering fetcher if you set `FIRECRAWL_API_KEY`.

## 6. Online editor

Publish with `--enable-editor`, then open the page with an editor token to
edit text and insert images in place — no redeploy:

```bash
export GOLIVE_EDITOR_TOKEN=$(openssl rand -hex 24)
golive publish report.html --slug q3 --enable-editor
# open: http://host:8787/q3?editor_token=<TOKEN>&editor_user=you@corp.com
```

Click **✏️** to enter edit mode, edit text, use **🖼 图片 / Image** to upload
(or inline when no image host is configured), then **💾 Save**. Every save
re-runs the security scan and writes a rollback snapshot. Only site owners
and maintainers may save (see next section).

## 7. Access control

Editing is limited to a site's **owner** (set at publish time) and any
**maintainers** you add:

```bash
golive maintainer add q3 alice@corp.com
golive maintainer list q3
golive maintainer remove q3 alice@corp.com
```

Identity comes from the OIDC session when logged in, otherwise from the
`editor_user` parameter validated against the editor token. A shared token
(single token, many editors) is supported but warns at publish time.

## 8. Built-in data storage

Give a static page a real key-value/record store via `window.TemplateAPI`
— no backend code. Namespaced records, list/get/create/update/delete/
upsert/sort.

```bash
golive publish app.html --slug app --data-model app_v1
golive serve
```

That is the whole setup: the default `sqlite` backend keeps rows in
`$GOLIVE_HOME/data.db` (table created on first use) and `golive serve`
exposes them to the page at `/api/data`. The page therefore has to be
loaded **through the server** — `file://` gives the data layer no
endpoint to call. Switch to Supabase when a dataset must be shared
across machines (section 9), or to **Postgres** when you have a
self-hosted PG instance (section 8a). Full API and examples:
[data-layer.md](data-layer.md).

Inspect or seed rows from the CLI:

```bash
golive data list   --model-code app_v1
golive data create --model-code app_v1 --name seed --content '{"n":1}'
```

## 9. Using Supabase

Point golive at your own Supabase project to get remote storage, a shared
registry, and the data layer — all three from one project:

```bash
golive db init --print-sql       # paste into Supabase SQL editor
```

Config and RLS notes: [backends.md](backends.md), [data-layer.md](data-layer.md).

## 8a. Using a self-hosted Postgres

When your team has a PostgreSQL instance on the intranet, you can use it
for the **data** and **registry** layers — no Supabase account needed.

```bash
pip install 'html-golive[postgres]'
export GOLIVE_PG_DSN='host=localhost dbname=golive user=postgres password=secret'
golive db init                   # creates tables on first run
```

In `golive.yaml`:

```yaml
data:
  backend: postgres
registry:
  backend: postgres
```

The DSN is read from the environment (never written to yaml) —
`GOLIVE_PG_DSN` by default, configurable via
`registry.postgres_dsn_env`. Tables auto-create on first use, same as
SQLite. Content is stored as JSONB; the external API (dict in, dict out)
is identical to the SQLite backend.

## 10. Doctor

`golive doctor` is the one command to run whenever something behaves
unexpectedly, and the one to run after every upgrade.

```bash
golive doctor                    # full report
golive doctor --port 9000        # probe a service on a non-default port
golive doctor --json             # machine-readable, for scripts and agents
```

```
🩺 golive doctor

golive           0.7.1                                （CLI）
running service  0.7.0  pid 12345  port 8787          ⚠️  版本不一致，建议重启
                 代码已更新（CLI 0.7.1）但服务还是旧的（0.7.0）—— 运行：golive serve restart
GOLIVE_HOME      /Users/you/.golive                   (from $GOLIVE_HOME)
storage          local → /Users/you/.golive/sites     （12 个站点, 4.2 MB）
registry         sqlite → /Users/you/.golive/registry.db  （12 个站点）
data backend     sqlite → /Users/you/.golive/data.db  （3 张表, 47 行, 96.0 KB）
skill            ~/.codex/skills/html-golive  0.7.1   ✅
admin portal     http://localhost:8787/admin
```

Line by line:

- **golive / running service** — the CLI version next to the version of
  the server actually answering on the port. When they differ you are
  looking at old code still in memory; `golive serve restart` fixes it.
  Not running is reported as `not running`, which is not an error.
- **GOLIVE_HOME** — the resolved data directory and where that value came
  from (`$GOLIVE_HOME`, a pointer file, or the default).
- **storage / registry / data backend** — each of the three layers with
  its backend type, real path, and size, so you can tell at a glance
  whether you are writing where you think you are.
- **skill** — every installed copy of the agent skill and whether its
  version matches this golive.
- **admin portal** — the URL, ready to click.

Missing dependencies and orphaned sites (a registry row with no content
file) are listed underneath. Exit code is `0` when healthy and `1` when
there is a blocking problem; a version mismatch is a warning, not a
failure.

## 11. Running as a background service

`golive serve` with no sub-action runs in the **foreground**, exactly as
it always has — `Ctrl+C` stops it. To keep it running after you close the
terminal, use the sub-actions:

```bash
golive serve start               # background; pidfile + log in GOLIVE_HOME
golive serve start --port 9000 --host 0.0.0.0
golive serve status              # running? which pid, port, version?
golive serve restart             # what you run after upgrading
golive serve stop                # SIGTERM, then SIGKILL if it hangs
golive serve logs -n 100         # last 100 lines
golive serve logs -f             # follow
```

State lives in `GOLIVE_HOME`: the pid and its metadata in `golive.pid`,
output in `logs/serve.log`.

Things that will not surprise you:

- A **stale pidfile** (the recorded process is gone) is detected and
  cleaned up automatically — it never blocks a start.
- A **second `start`** does not spawn a twin; it tells you the service is
  already up and suggests `restart`.
- A **port held by something else** is reported as such, distinct from
  "our own server is already there", because the fixes differ.
- A server you started in the **foreground** has no pidfile, so
  `serve stop` will say so and point you at `Ctrl+C` rather than killing
  a process it does not own.

## 12. Logs & audit

Every publish, update, rollback, and editor save is recorded in the audit
log under `GOLIVE_HOME/logs/`. Editor saves record the editor's identity,
the site, size, and the snapshot id created.

## 13. Security

- **Scanning**: every publish (and every editor save) is scanned for API
  keys, private keys, connection strings, and PII. Strong hits **block**
  the publish; weak hits warn. Extend with your own YAML rules or bypass a
  false positive with `--skip-scan`.
- **LLM review** *(optional)*: configure an OpenAI-compatible endpoint to
  have an LLM second-guess weak hits and cut false positives. Unset →
  skipped (rules still apply). Details: [security.md](security.md).
- **Watermark**: overlay a tiled identity/text watermark
  (`--watermark "CONFIDENTIAL"` or `watermark.enabled: true`). Identity can
  come from the logged-in OIDC user, a static string, or a page meta tag.
  Disable globally with `GOLIVE_WATERMARK_OFF=1`.

## 14. Sharing

```bash
docker compose up -d golive                 # serve on :8787
docker compose --profile minio up -d        # + local S3 for images
```

Put golive behind your reverse proxy / VPN to control who reaches it.
There is no built-in "publish to the public internet" step — you decide
the network boundary.

## 15. Backends

golive is built on three swappable interfaces — Storage, Registry, and
Images — plus an S3-compatible image uploader. Mix and match local,
Supabase, and S3. Configuration matrix and examples:
[backends.md](backends.md).

## 16. Identity & login

Serve mode supports three auth providers: `none` (default), `token`
(`GOLIVE_TOKEN`), and `oidc` (any OpenID Connect IdP). OIDC handles login,
callback (PKCE + state), a signed session cookie, and `/auth/me`. Use a
**preset** for common IdPs:

```yaml
auth:
  provider: oidc
  oidc:
    preset: google          # or auth0 / okta / azure / keycloak / authentik
    client_id: xxx.apps.googleusercontent.com
    redirect_uri: https://pages.example.com/auth/callback
```

Set the client secret via `GOLIVE_OIDC_CLIENT_SECRET` and a stable
`GOLIVE_COOKIE_SECRET` in production (otherwise golive persists one under
`GOLIVE_HOME`). Presets fill the issuer/scopes; explicit fields override.

**Token verification.** Since v0.8.0 every `id_token` is checked against the
IdP's published signing keys before a session is created: the signature must
verify, `iss` / `aud` / `exp` / `nonce` must all match, and `alg: none` is
refused outright. This needs the optional crypto dependency:

```bash
pip install 'html-golive[oidc]'
```

Without it golive refuses to start in OIDC mode rather than quietly skipping
verification. If your IdP cannot issue RS256 tokens you can set
`auth.oidc.verify_signature: false`, but the server will warn loudly at every
startup — an unverified token is one anybody can forge.

**Granting access after login.** Signing in proves who someone is; it does not
make them an operator. List admins under the `admin` section:

```yaml
admin:
  admins: [alice@corp.example]
```

A common slip is writing `admins:` at the top level, where it has no effect.
golive prints a warning naming the correct key when it sees this, so check
startup output if a login succeeds but the portal stays read-only.

**Behind a gateway.** Where policy forbids the app talking to the IdP directly,
`auth.provider: proxy` trusts an authentication header set by your gateway:

```yaml
auth:
  provider: proxy
  proxy:
    header: X-Forwarded-User
    trusted_ips: ["10.0.0.0/8"]
```

`trusted_ips` is mandatory — without it anyone able to reach the port could
forge that header. golive refuses to start if the list is empty.

## 17. Migrating pages

Moving a page built on another golive deployment (or an intranet one)?

```bash
golive migrate-check page.html      # reports deployment-specific references
```

It flags hard-coded API domains, deployment ids, and non-portable calls
with `file:line` and a suggested fix. Guide:
[migrate-from-intranet.md](migrate-from-intranet.md).

## 18. Admin portal

`golive serve` ships a web management portal at **`/admin`** (URL printed
in the startup banner, or `golive admin open`). Site owners and
maintainers manage their own sites; **superadmins** see everything plus
instance-wide stats and the audit trail.

Superadmins are declared by email:

```yaml
# golive.yaml
admin:
  admins: [ops@example.com]
```

or `GOLIVE_ADMINS=a@x.com,b@x.com` (env wins). A caller authenticated with
the static `GOLIVE_TOKEN` is also treated as superadmin — the token is
operator-held by definition. With zero auth configured the portal only
answers loopback requests (same rule as `/api/sites`).

**Two superadmin sources** *(v0.7)*. The declarations above are
**builtin** admins: read-only at runtime, so nobody can remove the
operator through the UI or API. Additional **managed** admins can be
added and removed at runtime and are stored in `registry.db`. The
effective superadmin set is the union of both, and
`GET /api/admin/me` reports `builtin` so the UI can hide *delete* on the
config-declared ones.

Permission endpoints (all superadmin-only):

| Endpoint | Purpose |
|---|---|
| `GET /api/admin/permissions` | builtin + managed admins, effective union, and every site's owner/maintainers |
| `POST /api/admin/permissions/admins` | add a managed superadmin (`{"email": ...}`) |
| `DELETE /api/admin/permissions/admins` | remove one — a builtin admin returns `400` with the config fix |
| `POST /api/admin/permissions/bulk` | grant/revoke `maintainer` (or grant `owner`) across many sites at once |

Bulk calls take `{"email", "role", "action", "slugs"}` and answer with
per-slug `applied` / `skipped` / `failed`, so one unknown slug never
aborts the batch. Revoking `owner` in bulk is refused — transfer the
site instead. Writes are audited as `perm.admin.add`,
`perm.admin.remove` and `perm.bulk`.

What you can do, by role:

| Action | owner | maintainer | superadmin |
|---|---|---|---|
| See the site in the list / details / snapshots | ✅ | ✅ | ✅ (all sites) |
| Edit name / notes / toggle online editing | ✅ | — | ✅ |
| Add / remove maintainers | ✅ | — | ✅ |
| Transfer ownership | ✅ | — | ✅ |
| Roll back to a snapshot | ✅ | ✅ | ✅ |
| Delete the site (type the slug to confirm) | ✅ | — | ✅ |
| Stats dashboard & audit log | — | — | ✅ |

Every write action (and every online-editor save) appends a line to
`GOLIVE_HOME/audit.log` — JSONL with who/action/slug/ts/detail, browsable
from the portal's Audit tab with slug/action filters.

**Audit rotation** *(M6)*: before each write, when `audit.log` exceeds
`admin.audit_max_bytes` (default 10 MB; env `GOLIVE_AUDIT_MAX_BYTES`;
`0` disables) it is renamed to `audit.log.1` and older archives shift up
(`.1` → `.2`, …), keeping `admin.audit_keep` generations (default 5; env
`GOLIVE_AUDIT_KEEP`). The portal's Audit tab and `GET /api/admin/audit`
read **only the current** `audit.log` — rotated archives are plain JSONL
files for operators to grep or ship elsewhere. A failed rotation never
blocks the write (the log just grows past the limit until fixed).

**Data management** *(M6, superadmin only)*: whenever a data backend is
active — `sqlite` by default, or `supabase` — the portal gains a data
tab that manages the TemplateAPI rows (`golive_templates`) shared by all
sites: pick a model from the dropdown (listed with row counts), search
inside the JSON content, view rows in a formatted dialog, edit them in a
JSON textarea (validated client-side before saving), add new rows, and
delete with a confirm. Every write is audited as `data.create` /
`data.update` / `data.delete`. Only with `data.backend: none` (or
Supabase selected without keys) does the tab show setup guidance
instead; the underlying endpoints live at `/api/admin/data/*` and return
`400 {"error": "no data backend configured"}` in that state.

The portal is a single self-contained page: no external CDN, no
framework, works on airgapped intranets. The same operations are
available as a JSON API under `/api/admin/*` for scripting.

### v0.8.0 admin pages: identity, data backend, security, settings

Four new superadmin-only pages were added in v0.8.0, completing the
management surface so operators never need to hand-edit `golive.yaml`
for day-to-day configuration.

**Identity & Auth** (`/admin → 身份认证`). Shows the current auth
method (none / token / oidc / proxy). The OIDC configuration form
includes an IdP preset dropdown (Google, Auth0, Okta, Azure AD,
Keycloak, Authentik, Custom) that auto-fills the issuer template —
only `client_id` and `client_secret` remain to fill in. The **Test
connection** button performs a real discovery fetch and reports the
endpoints and signing algorithms found, or gives an actionable error
message. The callback URL is prominently displayed with a copy button.
A "📋 Copy for your AI assistant" button generates a complete task
description with the real callback URL, IdP setup steps, and
verification instructions. Secret fields show a mask; leaving them
blank preserves the existing value.

**Data Backend** (`/admin → 数据后端`). Displays the current backend
type, location, table count and row count. A switch form lets you
pick a new backend (sqlite / supabase / none) and test the connection
before switching. A prominent warning makes clear that **data is not
migrated** when switching backends — export first if you need it.
Backend changes require a server restart.

**Security Scan** (`/admin → 安全扫描`). Shows the three scan layers
(keyword / regex / AI review) with their on/off status. The rule list
distinguishes built-in rules (locked, but can be disabled) from user
rules (full CRUD). The **Rule test run** lets you paste a text sample
and see which rules it triggers, with strength (block / warn), before
publishing. The AI review section configures the LLM endpoint, model,
API key, and strict mode, with a connection test button. Recent block
records are shown in a table.

**Global Settings** (`/admin → 全局参数`). Shows all configuration
settings grouped by section (server, auth, storage, data, security,
admin). Each item is annotated with its source — **file** (from
`golive.yaml`, read-only with an explanation), **database** (managed
override, can be deleted to fall back), or **default**. Settings with
`restart` scope are clearly marked as requiring a restart. Database
overrides can be removed individually, reverting to the file or
default value.

All four pages degrade gracefully when the v0.8.0 API endpoints are
not available (older server): they show a "requires 0.8.0+" notice
instead of a blank page or broken UI.

New API endpoints (superadmin-only, all audited):

| Endpoint | Purpose |
|---|---|
| `GET /api/admin/settings` | list all settings with source/scope |
| `PUT /api/admin/settings` | update one or more settings |
| `DELETE /api/admin/settings/<key>` | remove a database override |
| `GET /api/admin/security/rules` | list all security rules |
| `POST /api/admin/security/rules` | add a user rule |
| `PATCH /api/admin/security/rules/<id>` | update a rule (enable/disable, etc.) |
| `DELETE /api/admin/security/rules/<id>` | delete a user rule |
| `POST /api/admin/security/test` | test text against all rules |
| `POST /api/admin/test/oidc` | real OIDC discovery fetch |
| `POST /api/admin/test/data-backend` | test a data backend connection |
| `POST /api/admin/test/llm` | test the LLM endpoint |

## 19. AI agent skill

golive ships an AgentSkill so AI coding assistants drive it correctly
instead of guessing paths or mistaking it for a hosted deployment
service:

```bash
golive skill install          # auto-detect the agent's skills directory
golive skill install --target ~/.agent/skills
golive skill status           # installed vs packaged version
golive skill path             # bundled source, for manual copies
```

The skill is packaged inside the wheel, so installation needs no
network; `--from-github` pulls the latest copy instead, and falls back
with a clear message when offline. Installing over an existing copy
requires `--force`, which backs up the old directory first.

It teaches the agent to probe first (`golive --version`, `golive
doctor`, `$GOLIVE_HOME`, `golive list`), update existing sites by slug
rather than publishing duplicates, treat `--host 0.0.0.0` and
`--skip-scan` as explicit-request-only, and wire up `TemplateAPI`
correctly (including the `templateapi:ready` gate).

## 20. FAQ

**Do I need a server?** No — `golive publish` + a local file is enough.
`golive serve` adds a shareable URL and the online editor/data layer.

**Does anything leave my machine?** Not at publish/serve time. Only if you
configure a remote backend (Supabase/S3), clone a URL, or use the preview
Tailwind cache. See [Network behavior](../README.md#network-behavior).

**Can pages built elsewhere run here?** Yes — the `window.TemplateAPI` /
`window.SupabaseAPI` signatures are stable contracts. Run `migrate-check`
first to catch any deployment-specific references.

**How do I restrict who can edit?** Publish with `--enable-editor`, set an
editor token, and add maintainers. Only owner/maintainers can save.

**Where is my data?** Under `GOLIVE_HOME` (default `~/.golive/`): published
sites, snapshots, the SQLite registry, logs, and caches.
