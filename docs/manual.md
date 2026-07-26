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
10. [Doctor: diagnose & fix](#10-doctor)
11. [Logs & audit](#11-logs--audit)
12. [Security: scanning, blocking, watermark, LLM review](#12-security)
13. [Sharing: public mirror & Docker](#13-sharing)
14. [Backends: storage / registry / images](#14-backends)
15. [Identity & login (OIDC)](#15-identity--login)
16. [Migrating pages from another deployment](#16-migrating-pages)
17. [Admin portal](#17-admin-portal)
18. [FAQ](#18-faq)

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
upsert/sort. Backed by SQLite locally or Supabase remotely. Full API and
examples: [data-layer.md](data-layer.md).

## 9. Using Supabase

Point golive at your own Supabase project to get remote storage, a shared
registry, and the data layer — all three from one project:

```bash
golive db init --print-sql       # paste into Supabase SQL editor
```

Config and RLS notes: [backends.md](backends.md), [data-layer.md](data-layer.md).

## 10. Doctor

```bash
golive doctor            # environment & config health check
```

Reports Python/dependency status, `GOLIVE_HOME` writability, configured
backends and their reachability, and common misconfigurations with fixes.

## 11. Logs & audit

Every publish, update, rollback, and editor save is recorded in the audit
log under `GOLIVE_HOME/logs/`. Editor saves record the editor's identity,
the site, size, and the snapshot id created.

## 12. Security

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

## 13. Sharing

```bash
docker compose up -d golive                 # serve on :8787
docker compose --profile minio up -d        # + local S3 for images
```

Put golive behind your reverse proxy / VPN to control who reaches it.
There is no built-in "publish to the public internet" step — you decide
the network boundary.

## 14. Backends

golive is built on three swappable interfaces — Storage, Registry, and
Images — plus an S3-compatible image uploader. Mix and match local,
Supabase, and S3. Configuration matrix and examples:
[backends.md](backends.md).

## 15. Identity & login

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

## 16. Migrating pages

Moving a page built on another golive deployment (or an intranet one)?

```bash
golive migrate-check page.html      # reports deployment-specific references
```

It flags hard-coded API domains, deployment ids, and non-portable calls
with `file:line` and a suggested fix. Guide:
[migrate-from-intranet.md](migrate-from-intranet.md).

## 17. Admin portal

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
from the portal's Audit tab with slug/action filters. The file is never
rotated automatically; archive it as you see fit.

The portal is a single self-contained page: no external CDN, no
framework, works on airgapped intranets. The same operations are
available as a JSON API under `/api/admin/*` for scripting.

## 18. FAQ

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
