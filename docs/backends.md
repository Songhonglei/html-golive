# Backends

golive separates concerns into three swappable interfaces plus auth.
v0.1 ships the zero-config defaults; adapters land in M2.

## StorageBackend

Stores published site content.

| Impl | Status | Notes |
|---|---|---|
| `local` | ✅ v0.1 | `$GOLIVE_HOME/sites/<site_id>/index.html`, snapshots in `backups/` |
| `s3` | 🚧 M2 | MinIO / any S3-compatible object storage |

Required methods (see `golive/backends/storage/local.py`):
`publish(html, site_id)`, `read(site_id)`, `exists(site_id)`,
`delete(site_id)`, `list_snapshots(site_id)`, `rollback(site_id, ts)`.

## RegistryBackend

Site metadata: id, name, slug, timestamps, owner.

| Impl | Status |
|---|---|
| `sqlite` | ✅ v0.1 |
| `postgres` | 🚧 M2 |
| `supabase` | 🚧 M2 |

Required methods (see `golive/backends/registry/sqlite_store.py`):
`create`, `update`, `touch`, `delete`, `get`, `get_by_slug`, `resolve`,
`list_all`, `slug_taken`.

## DataBackend (M2)

Provides the in-page `window.TemplateAPI` / `window.SupabaseAPI` data
layer for dynamic dashboards. The JS signatures are stable — pages built
against them run unchanged across implementations.

## ImageUploader

Turns bundled images into public URLs instead of base64 data URIs.
Zero-config default: no uploader, everything is inlined.

| Impl | Status | Notes |
|---|---|---|
| *(none)* | ✅ v0.1 | default — images inlined as base64 |
| `command` | ✅ v0.1 | shell-command template, works with any image host |
| `s3` | 🚧 M2 | native S3/MinIO uploader |

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

Examples:

```bash
# any CLI that prints a URL
export GOLIVE_UPLOADER_CMD='imgcli put {file}'

# S3 via AWS CLI (until native s3 lands in M2)
export GOLIVE_UPLOADER_CMD='sh -c "aws s3 cp {file} s3://bucket/img/{name} >&2 && echo https://cdn.example.com/img/{name}"'

golive publish ./my-project/ --name Demo
```

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
signatures identical, and wire it up in `golive.yaml` (backend selection
loading lands with M2's config loader).
