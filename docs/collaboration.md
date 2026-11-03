# Team collaboration (P2 development)

Tracked in [#16](https://github.com/Songhonglei/html-golive/issues/16), on a separate P2 branch based on PR #14. These changes are not a published release or a change to the fixed P1 acceptance baseline. Pin the commit and installed artifact when validating.

## Conditional editing

Local page storage now serializes all `publish`, conditional editor saves and deletes across server/CLI processes using the same HOME. Saves compare the stored HTML's SHA-256 revision under that lock, then snapshot and atomically replace the file. Published pages carry a transient revision meta tag for exactly the content served. The injected editor removes this tag before uploading.

An editor with an old revision receives HTTP **409**, `code: edit_conflict`, and `current_revision`. The saved page and its snapshots are unchanged. The browser retains the local draft and opens a comparison with the latest server HTML. Copy or merge the draft, then reload; retries never automatically adopt a newer revision. No automatic merge or force-write button is provided.

For an Agent:

1. Authenticated `GET /api/sites/<slug-or-id>/content` returns `{html, revision}` and `ETag` (`Cache-Control: no-store`). Use the existing editor token + personal `X-Editor-User`, or an OIDC session.
2. `PUT` to the same URL with `Content-Type: text/html` and **`If-Match: <revision>`**, including its double quotes. Successful saves return their new `revision`.
3. Missing `If-Match` returns **428**, `revision_required`; malformed/weak/wildcard revisions return **400**, `invalid_revision`. On 409, read again, compare and explicitly merge before retrying.

Existing custom save clients must adopt this contract. Re-publish legacy pages to update their injected editor script; a legacy client receives 428 instead of silently overwriting newer content. The security scan and ACL checks remain mandatory.

Atomic conditional editing currently requires **local storage on macOS/Linux**. `storage.backend=s3` or `supabase` returns **501**, `conditional_write_unsupported`, for editor saves; reads and normal publishing remain supported. The data/registry backend can independently be SQLite, MySQL, PostgreSQL or Supabase. Remote storage needs a native conditional-write implementation before online editing is enabled there. Direct filesystem writes and multiple independent HOMEs are outside the lock contract. CLI publishing and rollback remain explicit unconditional operations; stale editors are rejected after their content changes. Reverting to byte-identical content yields the same hash revision.

## Groups and inheritance

In **Admin → Permissions → Team groups**, superadmins create groups, add/remove member emails and grant/revoke site access. Group IDs are immutable; deleting and recreating the same name does not restore old members or grants. Site grants use immutable site IDs, so changing a slug does not change access.

Effective permissions are additive: superadmin > personal owner > personal maintainer > group maintainer > group viewer > no admin access. Any maintainer grant wins over viewer grants. Revoking membership or a group grant only removes that inherited access; independent personal and other-group grants remain. Groups cannot own sites, grant superadmin status, edit site metadata, transfer ownership, delete sites or manage ACLs. A maintainer can save editable content, upload and roll back; a viewer can inspect the admin site list/detail and snapshots but cannot write. These grants do **not** make public static pages private or add row-level business-data authorization.

Group membership uses only the server's OIDC session email, not `X-Editor-User`, headers, token claims or a client's `groups` list. Configure a trusted IdP with unique controlled emails; external directory/group-claim synchronization is not implemented. An editor bearer token retains the existing personal owner/maintainer contract; claiming a group member email with it does not grant inherited access. A group's membership/grants are read on every request, so an existing login loses access on its next request after revocation. Already returned HTML cannot be revoked. Group-store failure denies inherited permissions; personal admin roles remain independent.

For ownerless sites, adding the first group grant permanently disables the legacy open editor-token mode for that site ID, including after the last grant/group is removed. Set an explicit owner/maintainer to restore a personal editing path.

## Management API and audit

All endpoints below require the existing superadmin identity. User-controlled actor fields are ignored.

| Method | `/api/admin/permissions/groups` suffix | Body / result |
| --- | --- | --- |
| GET | empty | `{groups:[{id,name,members,grants}]}` |
| POST | empty | `{name}` → immutable `group_id` |
| DELETE | `/<id>` | Remove group, members and grants |
| POST / DELETE | `/<id>/members` | `{email}` → add / remove |
| POST / DELETE | `/<id>/sites` | `{site: slug-or-id, role: viewer-or-maintainer}` → grant/update / revoke (role ignored for revoke) |
| GET | `/audit?limit=100&before=<event-id>` | Durable events newest first; continue with `next_before` until null; max page size 200 |

Mutations return `{success,changed,group_id}`. Repeated add/grant/remove is idempotent where the referenced group exists. Unknown group/site returns 404; malformed input or invalid role returns 400; unavailable storage returns 503 without internal paths. A missing authenticated admin identity is rejected by the outer admin API with 401, a non-admin with 403.

Tables are created additively in this instance's `$GOLIVE_HOME/registry.db`, beside `managed_admins`; changing remote registry/data backends does not move them. Each actual group change and its audit event commit in one SQLite transaction; audit failure rolls back the change. The existing JSONL admin audit also receives a summary, using its existing best-effort behavior. Durable group events are available through `/groups/audit` independently of JSONL rotation.

Existing personal ACLs need no conversion. No group is auto-created or auto-populated. Back up the local management database separately: portability exports do **not** include groups, membership, grant guards or group audit (as with managed admins). A full deployment restore must preserve this management state. Shared management state, shared sessions and consistent revocation across independent instances remain P3.
