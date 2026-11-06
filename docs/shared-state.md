# Same-host shared login and control state (P3)

Candidate development feature, stacked on P2; not yet released. Two server
processes on **one host with local disk** can keep separate `GOLIVE_HOME`s while
sharing login and permissions. This avoids logging in again when a local reverse
proxy switches processes. No Redis or other mandatory infrastructure is added
to single-instance installations.

## Configuration and contract

Set the same absolute `GOLIVE_STATE_DIR` in **every** server/CLI process before
startup, for example `/srv/golive/control`. This is a bootstrap environment
option, deliberately outside YAML/database overrides: resolving an authentication
database must not depend on reading that same database. Omit it for existing
single-instance layout. New directories/files use 0700/0600; existing directories
are not chmodded. The operator must restrict all parent paths and backups.

Both processes need the same OIDC issuer, client ID, redirect URI, signing key
and token/admin configuration. Use a single public gateway origin and callback;
the IdP must permit its exact callback URL. Cookies use the existing host-scoped
HttpOnly, SameSite=Lax policy; HTTPS deployments require Secure cookies and a
trusted TLS-terminating proxy. Arbitrary domains do not share cookies.

Shared files:

| File | Contents / behavior |
| --- | --- |
| `.cookie_secret`, `.cookie_secret.lock` | Stable generated key; concurrent initialization uses a file lock. Explicit key env/config still takes precedence; all processes must agree. |
| `sessions.db` | Durable sessions and pending state/PKCE/nonce, separated by issuer/client/signing-key realm. Identifiers hashed at rest; user/PKCE values still sensitive. Expiry checked on read; expired rows pruned on writes. |
| `management.db` | Managed superadmins, groups, members, site grants, persistent guard and transactional group audit. Changes read at the next request, without an authorization cache. |

Sessions now persist across restart in the default single-instance HOME too.
Pending login consumption is a SQLite transaction: one callback wins even across
processes; token exchange failure consumes state and requires a new login.
Logout deletes server-side state before confirming success. Store failure gives
HTTP 503, not a successful local-only logout; configured OIDC refuses startup
on misconfiguration/store initialization failure. Expired or different-realm
cookies authenticate nobody. Managed-admin and group revocation leaves the
login valid while removing the corresponding permissions.

## Local dependency inventory

`golive context --json` and `golive doctor --json` expose `local_state`: resolved
directory/source, paths, remaining local components and limitations. Context
does not create HOME/control directories or read secret contents. The text
context also identifies an explicitly shared control root.

| Component | P3 behavior / deployment responsibility |
| --- | --- |
| Login/key, groups and managed admins | Shared by this opt-in; group events commit with permission changes. |
| Registry and personal site ACL | Still selected by `registry.backend`; use the same remote registry for a logical service. A separate SQLite HOME is separate metadata. |
| Page files and content snapshots | Still selected by `storage.backend`; use the same remote storage or preserve existing single-HOME local storage. WebDAV does not add conditional editor writes. |
| Template/data rows | Still selected by `data.backend`; use the same database explicitly. |
| YAML, secrets, builtin admins/token, global settings | Per instance. Settings remain in each HOME's registry.db; apply matching security/config to all processes and restart when required. |
| Scan/rule/manifest stores | Per HOME; not replicated by shared login. |
| PID/health identity, service logs, general audit.log | Per HOME; service-record PID/HOME safety is unchanged. Group audit alone is shared. Aggregate general logs externally. |
| CSS/Tailwind/localization caches, uploads/external resources | Existing per-HOME/provider paths; coordinate or rebuild separately. |
| Background jobs/process lifecycle | No distributed scheduler, leader election or cross-instance stop/restart. |

This feature does **not** make two otherwise independent deployments one logical
service. It supplies shared authentication/control state. Consistent config,
registry/page/data stores, gateway routing and operational metadata need their
own deployment plan. SQLite on NFS/SMB, cross-host failover and production load
balancers have no acceptance claim.

## Offline adoption, backup and rollback

There is no automatic merge of operator state. Before enabling the environment
option, stop the participating processes, back up the original HOME(s) and
select one authoritative control state. Resolve any differences explicitly.
Starting with an empty shared management database means empty managed/group
permissions; it does not import local guards or grants automatically.

Create a fresh private control directory. Use SQLite's backup API (or an offline
copy of a cleanly stopped database) to copy the authoritative `registry.db` to
`management.db`; this preserves all group/guard/admin tables and group audit.
Extra registry/settings tables in that copy are inert: they do not become the
active site registry/global settings. Copy `.cookie_secret` and `sessions.db`
when present, maintaining 0600 permissions. An explicit configured signing key
must remain consistent. Enable the environment option everywhere, then check
login, permissions, logout and `local_state` before opening the gateway.

Portability export/import does **not** include these files, identity-provider
credentials, general logs, config or secrets. Back up control state separately
and consistently, protecting session/key material. A restored DB can resurrect
old unexpired sessions: rotate the signing key to invalidate them when required.

Rollback requires coordinated stop and backup. Removing `GOLIVE_STATE_DIR`
reselects each HOME's old local control state, potentially restoring stale grants.
Do not roll back by merely unsetting the variable on one process. Reconcile the
authoritative control database offline and revalidate permissions first.

Validation and actual boundaries: [P3 validation](validation-p3.md).
