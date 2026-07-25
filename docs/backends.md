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
