# DATA-01 restore identity validation

Baseline: 0.9.8 candidate source `7b9f7b9`, with an independent failing check on
the previously accepted installed `f0de446` wheel. Development is tracked in
[#11](https://github.com/Songhonglei/html-golive/issues/11).

## Contract

Archive import and data migration use an internal `restore_row` backend method,
separate from ordinary CRUD. It restores business ID, model/name/user, description,
JSON content (including scalars/null), version, sort index and created/updated
instants. SQL parameters bind values; PostgREST writes explicit fields.

Empty targets preserve cross-row ID references without rewriting opaque JSON.
Repeated `skip` imports retain IDs; metadata/content differences are reported as
non-exact. `overwrite` restores the same identity and refuses conflicting IDs or
logical keys. `rename` reports new IDs and explicitly does not remap references.
Identical migration targets are skipped; differing targets are not overwritten.
New registry migration entries retain their source site IDs.

Archive parsing, counts, duplicate IDs/keys, metadata, duplicate tar members and
non-regular entries are checked before a target is opened. Preview is archive-only
and reports unknown target conflicts. Import reports partial/uncertain writes and
readback failures; exceptions do not expose driver DSNs/content. Import/migrate
JSON modes return nonzero on operation failure and include stable operation/result codes;
argument parsing and global config loading retain existing CLI behavior (AUTO-01 follow-up).
SQLite factories now use the explicitly supplied database/table configuration.

## Evidence

Local private logs and scripts are retained under `.artifacts/p1-data01/`.
The baseline regression restores into a separate SQLite target using the old
installed wheel: reading an original record ID returns `None` (expected failure).
The development regression requires the same original ID, linked content, order,
metadata and repeated-import result to agree.

Runtime fix baseline: `d28f4a87da5e868a5a4ba27fcfd404076596ec4d`.
The first `beaa412` CI artifact failed PostgreSQL scalar-string restoration:
psycopg had already decoded JSONB and a second decode changed plain strings.
That artifact is retained as rejected, not accepted. The fix distinguishes decoded
PostgreSQL JSONB from MySQL/SQLite JSON text; JSON-looking scalar strings remain strings.

| Check | Actual result |
| --- | --- |
| Local source suite at runtime baseline | 1235 passed, 125 skipped, 643 subtests passed (121.06s) |
| Source isolated MySQL contracts | 86 passed, 29 skipped; 27 actual MySQL cases, including negative migration conflicts |
| Fresh installed-wheel contracts from sdist tests | 86 passed, 29 skipped; 27 actual MySQL cases |
| Independent installed lifecycle CLI | 16 commands passed; unrelated sleeper preserved |
| Installed MySQL 8.4.13 + Chrome | All 16 full stages passed, with browser/SQL/admin/restart evidence |
| Installed old-release upgrade, exact restore and code rollback | All 11 checks passed; zero record-ID limitations in this fixture |

Real database integrations are not counted as passed when DSNs are absent.
CI runs real PostgreSQL/MySQL and Supabase/PostgREST/Storage/RLS contracts and
migration round trips. Follow-up tests add negative migration conflicts and
live Supabase scalar/metadata restoration; final check status is recorded in PR #12.
The fake PostgREST runs above remain distinct from actual Supabase CI evidence.

The upgrade fixture installed the published 0.9.7.post1 wheel, exported a row with
historical timestamps and sort index 73, installed the exact new wheel while the
old process remained running, verified version drift, restarted the candidate, restored into a
new database and downgraded code. Page hashes, original record ID and
all business fields matched. Independent MySQL SELECTs confirmed ID/content/order/
timestamps in the restored database; code rollback read candidate-written rows.
Configuration was copied separately. All self-created services stopped and the
native MySQL sandbox was cleaned; previous acceptance resources were not touched.

CI artifact ID `13223464958` from
[run 41622322298](https://github.com/Songhonglei/html-golive/actions/runs/41622322298)
was downloaded and hash-verified. Source commit is the runtime baseline above;
GitHub checkout merge commit is `0cdfb3cdcdddadff8be0ec74e4b96546a333385f`.
Outer artifact ZIP SHA-256:
`d7511f9110f6186e36dff4986615e1c52598de6b77dbfd4df1fe9b4db3790d62`.

| Distribution | SHA-256 |
| --- | --- |
| `html_golive-0.9.8-py3-none-any.whl` | `3def485bbad91deae52d4edf7a3acf936ede3a1e90b1cee0270c66affb028ef0` |
| `html_golive-0.9.8.tar.gz` | `0644a268705cf2c9a3b162d9c1f5b0cf19505e1591b0c910d5b4c5a0ea0845d8` |
| `html-golive-skill-0.9.8.zip` | `49815230d096b6b38c5cbc2dbf2faa05f70c0d1d46d5b8d36b12ee45da92225e` |

All 121 installed runtime files matched the wheel and source; CLI/module/distribution/
health/bundled Skill versions agree at 0.9.8. Installation ran outside the checkout.
The installer omitted optional archive hashes in `direct_url.json`; the receipt
supplements its file URL with independently verified SHA-256 and installed bytes.
Later test/documentation-only changes do not replace this artifact identity.

Local evidence includes `installed-provenance.json`, `installed-mysql-results.xml`,
`mysql-full/`, `lifecycle/` and `upgrade/` reports/CLI logs/SQL/backup under the private
`.artifacts/p1-data01/` directory. No registry upload, tag, release or business
service/database modification was performed.

## Limits

This fixes business record identity; it is not archive-wide transactionality or a
complete machine snapshot. Legacy missing metadata is defaulted and reported,
not called exact. Registry timestamps, audit/session/Agent state, page revision
history, configuration, credentials and external resources require separate
recovery handling. A rename operation or skipped different target may leave
references to different/missing records; inspect the report and application.

Source writers must be paused for a consistent multi-resource backup. Large-data
count/search caps remain DATA-02 work. Docker sandbox and remote MySQL TLS remain
unverified. The accepted `f0de446` artifact is historical and does not acquire this
fix merely because it shares the candidate version string.

See the executable steps and boundaries in the [recovery runbook](recovery.md).
