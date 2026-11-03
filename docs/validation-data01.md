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

Final source, real MySQL and installed-artifact results will be recorded here
when those runs finish. External integration cases are not counted as passed
when their DSNs are absent. Real Supabase CI exercises PostgREST/Storage/RLS plus
SQL migration round trips; a fake PostgREST run is labelled separately.

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
