# P3 development validation

Baseline: P2 `a21ae3b2131d6a12bff78cfc6110a21f4bd77c4f` (PR #17).
Tracking: [#19](https://github.com/Songhonglei/html-golive/issues/19).
Branch: `codex/p3-shared-state-webdav`, stacked on P2. Candidate package remains
unpublished `0.9.8`; use exact commit/manifest hashes rather than version alone.
No merge, release, business deployment or existing acceptance-resource changes.

## Implemented scope

- [Same-host shared state](shared-state.md): durable OIDC sessions, pending
  PKCE/nonce/state, locked cookie-key initialization, realm isolation, atomic
  state consume, next-request logout/group/managed-admin revocation, private
  files and failure-closed HTTP/startup behavior. Explicit optional environment
  path; existing single-instance permissions layout preserved.
- Read-only local-state dependency inventory in context/doctor JSON; offline
  adoption, backup, reset and rollback boundaries documented.
- [WebDAV storage](webdav.md): factory/config integration, server-side environment
  credentials, verified TLS, timeouts, scoped publish/read/delete, ten snapshots,
  rollback, no redirects/cache, untrusted XML/path/response-size handling and
  explicit unsupported remote editor CAS (501).

## Reproducible automated checks

```bash
python -m pytest tests/test_shared_state.py tests/test_shared_http.py \
  tests/test_webdav.py tests/test_webdav_live.py -q --timeout=45
python -m pytest tests/ -q --timeout=45 --timeout-method=signal
```

`test_shared_http.py` launches two real child processes with independent HOME
and a shared local control directory. A controlled HTTP IdP signs RS256 tokens
and checks PKCE; `/auth/login` on A completes on B. Tests verify state replay,
process restart during pending login/after login, group/admin revocation and
logout across both, then DB-corruption 503 responses. Registry/pages are
identical isolated fixtures, not a content-replication claim. All children and
servers stop during fixture teardown; only their own processes can be signalled.

`test_shared_state.py` also runs six competing processes for one state key
(one winner), concurrent initial key creation, expiry/different realm/key,
private file modes, read-only inventory, default paths and failed startup.

`test_webdav.py` uses real loopback HTTP with controlled failures: auth, redirects,
locks/capacity/server errors, partial delete, unsafe endpoint/site/snapshot paths,
foreign hrefs, bad XML, oversized bodies and preservation after failed read/PUT.
`test_webdav_live.py` uses actual WsgiDAV with a fresh local CA and TLS server:
valid CA succeeds; untrusted CA/wrong hostname fail; lifecycle/retention/rollback,
wrong credentials and scoped deletion are checked. It explicitly skips unless
WsgiDAV is installed; the dedicated **P3 CI job** installs it and executes it.
The normal package has no new runtime dependency.

Installed validation uses the exact CI wheel/sdist and manifest, a fresh venv,
and [the source-free suite runner](../scripts/verify_installed.py). Runtime bytes
must match both archives; tests/docs come from that same sdist, with no Golive
Python source copied alongside tests. The existing full installed CI gate and
real database jobs remain required. Test counts, artifact hashes and browser
receipts for the final commit are recorded in the PR and ignored task evidence
directory `.artifacts/p3/`; this document does not pre-label unrun checks passed.

## Explicit boundaries

Same-host local-disk control sharing is the accepted design scope. Cross-host
HA, SQLite on NFS/SMB, distributed jobs, production gateway routing and external
IdP exchange are not covered by local two-process tests. Per-instance
config/settings, site metadata, pages/data, scans/rules and general audit logs
are not implicitly replicated. Control state is excluded from portability
exports and requires separate protected backup.

The controlled WebDAV/TLS server does not establish compatibility with a
specific NAS/Nextcloud version, external TLS/proxies, or production concurrency.
Remote protected editor writes stay unsupported (501); unconditional remote
publish/rollback are single-writer operations. Existing P2 acceptance reports
and their failed historical conclusions remain unchanged.
