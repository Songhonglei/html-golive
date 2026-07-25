# Backends

golive separates concerns into three swappable interfaces plus auth.
Everything is selected in `golive.yaml` (see `golive.example.yaml`);
zero-config means local + SQLite + built-in server.

## StorageBackend

Stores published site content.

| Impl | Status | Notes |
|---|---|---|
| `local` | ✅ v0.1 | `$GOLIVE_HOME/sites/<site_id>/index.html`, snapshots in `backups/` |
| `s3` | ✅ v0.2 | MinIO / COS / OSS / TOS / AWS — `pip install 'html-golive[s3]'` |
| `supabase` | ✅ v0.2 | Supabase Storage bucket (default `golive-sites`) |

Required methods (see `golive/backends/storage/local.py`):
`publish(html, site_id)`, `read(site_id)`, `exists(site_id)`,
`delete(site_id)`, `list_snapshots(site_id)`, `rollback(site_id, ts)`.

All three implementations keep the same rollback contract: max 10
snapshots per site, rollback itself snapshots the current version.
Remote backends (`s3` / `supabase`) add a 60 s in-memory read cache for
serve mode.

## RegistryBackend

Site metadata: id, name, slug, timestamps, owner.

| Impl | Status | Notes |
|---|---|---|
| `sqlite` | ✅ v0.1 | `$GOLIVE_HOME/registry.db` |
| `supabase` | ✅ v0.2 | PostgREST table `golive_sites` |
| `postgres` | 🚧 | direct DSN; use `supabase` (PostgREST) meanwhile |

Required methods (see `golive/backends/registry/sqlite_store.py`):
`create`, `update`, `touch`, `delete`, `get`, `get_by_slug`, `resolve`,
`list_all`, `slug_taken`.

## DataBackend

Provides the in-page `window.TemplateAPI` / `window.SupabaseAPI` data
layer for dynamic pages. The JS signatures are stable — pages built
against them run unchanged across implementations. Full guide:
[data-layer.md](data-layer.md).

| Impl | Status | Notes |
|---|---|---|
| `none` | ✅ | default — pages using the APIs get a stub with clear errors |
| `supabase` | ✅ v0.2 | PostgREST table `golive_templates` |

## Backend combos — worked examples

### 1. Pure local (zero config)

No `golive.yaml` at all:

```bash
golive publish page.html --name Demo --slug demo
golive serve   # http://localhost:8787/demo
```

### 2. Pure Supabase (one project hosts all three layers)

```yaml
# golive.yaml
supabase:
  url: https://YOURPROJECT.supabase.co
storage:
  backend: supabase        # HTML in Storage bucket golive-sites
registry:
  backend: supabase        # metadata in table golive_sites
data:
  backend: supabase        # TemplateAPI rows in golive_templates
```

```bash
export GOLIVE_SUPABASE_SERVICE_KEY=eyJ...   # server-side (CLI/serve)
export GOLIVE_SUPABASE_ANON_KEY=eyJ...      # embedded in injected JS
```

One-time setup:

1. Tables: `golive db init --print-sql` → run in the SQL Editor.
2. Storage bucket: create `golive-sites` in Dashboard → Storage
   (public bucket if you want direct object URLs).

Multiple machines / CI can now publish to the same deployment — state
lives entirely in Supabase.

### 3. Local + S3 image host

Keep sites local, upload bundled images to any S3-compatible store:

```yaml
uploader:
  s3:
    endpoint: http://localhost:9000    # MinIO from docker-compose --profile minio
    bucket: golive-img
    prefix: img/
    public_base: http://localhost:9000/golive-img
```

```bash
export GOLIVE_S3_AK=golive GOLIVE_S3_SK=golive-secret
pip install 'html-golive[s3]'
golive publish ./my-project/ --name Demo
```

### Table schemas & RLS

`golive db init --print-sql` prints both schemas with commented example
RLS policies:

- `golive_sites` — registry. With a **service_role key** (server-side
  only) RLS is bypassed; with an anon key add explicit policies.
- `golive_templates` — data layer. The injected JS uses the **anon
  key**, so RLS policies are **mandatory** — start from the examples in
  the printed SQL and tighten to your needs (e.g. restrict
  update/delete to authenticated roles).

## ImageUploader

Turns bundled images into public URLs instead of base64 data URIs.
Zero-config default: no uploader, everything is inlined.

| Impl | Status | Notes |
|---|---|---|
| *(none)* | ✅ v0.1 | default — images inlined as base64 |
| `command` | ✅ v0.1 | shell-command template, works with any image host |
| `s3` | ✅ v0.2 | native S3/MinIO/COS/OSS/TOS — `pip install 'html-golive[s3]'` |

Selection order: env `GOLIVE_UPLOADER_CMD` → yaml `uploader.command` →
yaml `uploader.s3.bucket` → none (base64).

### CommandUploader

Configure a command template via env `GOLIVE_UPLOADER_CMD` (wins) or
`golive.yaml`:

```yaml
uploader:
  command: "mytool upload {file}"
```

How it works:

1. golive writes the image to a temp file;
2. the template is shlex-split, then `{file}` (temp path) and `{name}`
   (original filename) are substituted per token — no shell involved;
3. the command runs with a **60 s timeout**;
4. the **last stdout line** starting with `http(s)://` is used as the URL.

Failures (non-zero exit, timeout, no URL on stdout) never break a
publish: the image **falls back to base64 inlining with a warning**.

### S3Uploader

```yaml
uploader:
  s3:
    endpoint: https://s3.example.com   # empty = AWS default endpoints
    bucket: golive-img
    prefix: img/
    access_key_env: GOLIVE_S3_AK
    secret_key_env: GOLIVE_S3_SK
    public_base: https://cdn.example.com   # returned URL prefix
```

Objects are keyed by content hash (`img/<sha256-16><suffix>`), so
identical images dedupe naturally. Returned URL:
`{public_base}/{key}`, falling back to `{endpoint}/{bucket}/{key}`
(path-style, MinIO-friendly).

Interface (`golive/backends/images/base.py`):
`upload(data: bytes, filename: str) -> str` — return a public URL or
raise `UploadError`.

## AuthProvider

| Impl | Status | Notes |
|---|---|---|
| `none` | ✅ v0.1 | default; fine for localhost |
| `token` | ✅ v0.1 | static token via `GOLIVE_TOKEN`, guards `/api/sites` |
| `oauth` | 🚧 M3 | enterprise SSO |

Interface: `verify(request_headers) -> bool`, `identity(request_headers) -> str`
(see `golive/backends/auth/base.py`).

## Writing your own adapter

Subclass the reference implementation's public surface, keep method
signatures identical, and register it in
`golive/backends/factory.py` (or monkey-patch `get_storage` /
`get_registry` in a wrapper script). Cloud-vendor Supabase-alikes that
speak PostgREST usually work with the `supabase` backends as-is — point
`supabase.url` at the compatible REST root.
