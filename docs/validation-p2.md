# P2 collaboration validation

Issue [#16](https://github.com/Songhonglei/html-golive/issues/16). Development branch `codex/p2-collaboration-groups`, based on P1 fix `6c6532296bbe24e4e3c39ddaad8a3c2332a7384b`; separate from the published package and fixed P1 acceptance result. No production database, acceptance HOME, existing service or container is used.

## Scope

See [collaboration contract and API](collaboration.md). This slice delivers conditional editing for local storage, browser conflict comparison with retained drafts, explicit OIDC-email groups, additive viewer/maintainer site grants and transactional change audit. Remote object-storage conditional editing and independent-instance shared permissions/sessions remain outside this slice.

`tests/test_collaboration.py` covers concurrent threads/processes (exactly one successful conditional write), missing/malformed/stale revisions, publish/rollback/delete invalidation, failed atomic replacement, untouched rejected content/snapshots, remote storage refusal, HTTP reads/writes, signed-session inherited permissions, denial/forgery, viewer restrictions, group/member/grant revocation, personal/group precedence, same-name recreation, ownerless-site revocation, persistence, idempotency, store failure and durable audit failure/pagination.

`test_team_grants_and_conditional_edit_with_registry` in `tests/test_backend_http_contract.py` also exercises actual configured registry instances. SQLite runs locally; PostgreSQL/MySQL cases require dedicated test DSNs and run in their existing CI jobs. Group management state itself remains in local SQLite for all registry/data backends. Supabase group-specific real-stack acceptance is not claimed by passing unrelated Supabase tests.

## Repeatable source checks

```bash
python -m compileall -q golive
python -m pytest tests/test_collaboration.py tests/test_editor.py \
  tests/test_permissions_api.py tests/test_admin_api.py tests/test_admin_ui.py \
  tests/test_write_paths_scanned.py tests/test_backend_http_contract.py -q
python -m pytest tests/ -q --timeout=45 --timeout-method=signal
```

The original editor round-trip now reads/sends its revision. Existing script-idempotency assertions count actual script IDs rather than references inside JavaScript. The security write-path accounting guard recognizes both `publish` and `publish_if_revision`; the count remains one scanned editor write path. First full run exposed this guard's old method-name assumption; its failure is retained rather than classified as a product pass.

## Browser and installed acceptance

Use a fresh directory and source-free installed wheel. Record commit, wheel hash, `direct_url.json`, Python executable and module location. Copy matching tests outside the checkout, then run the focused contracts with the installed interpreter. Do not install the same-version public package as a substitute.

In a fresh local HOME, issue test-only signed OIDC sessions (external IdP login is not exercised):

1. In the actual admin UI, create a group, add a member and grant maintainer on an editable site.
2. Open two browser tabs before either save. Save A, then save B. A succeeds; B shows a conflict dialog, retains its local DOM/draft and displays A's current server content. Closing the dialog retains B's draft. Copy/merge and explicitly reload before retrying.
3. Revoke that member in the admin UI. Reuse the existing member session: content reads/saves and admin site access are denied on the next request. Group-role viewer can inspect admin site details but cannot write/rollback/manage ACLs.
4. Validate group removal and durable audit, English/Chinese labels, mobile/desktop layout and browser errors. Stop only the test-created service; preserve the evidence and fixture HOME.

Task-local raw logs, JUnit XML, browser receipts/screenshots and artifact provenance live under `.artifacts/p2-collaboration/` (ignored). Final counts and fixed-commit CI/installed results are recorded in the PR and the local validation receipt after execution. Original P1 acceptance evidence is unchanged.

## Boundaries

- This is single-instance collaboration. Separate HOMEs, shared sessions, external directory synchronization and IdP code exchange need separate acceptance.
- S3/Supabase editor writes explicitly return 501 until native conditional writes exist; regression checks cover refusal, not remote storage integration.
- Public HTML and the existing business-data API do not become private/row-authorized through group grants.
- Operator-local groups and audit are excluded from portability archives; back up local management state separately.
- No merge, release or business deployment is authorized by these checks.
