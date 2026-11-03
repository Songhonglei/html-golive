# F01: compressed archive validation and error classification

Review baseline: `b7e89ab3bccdd42d1fdbe118c2ae18511c0c364a`, candidate 0.9.8,
[PR #14](https://github.com/Songhonglei/html-golive/pull/14),
tracked as [#15](https://github.com/Songhonglei/html-golive/issues/15).

The independent 2026-11-03 P1 acceptance report is valid: a valid export truncated
to 100 bytes raises `EOFError`, but the archive-validation boundary did not
normalize that exception. Both `import --dry-run --json` and `import --yes --json`
reported `backend_error` with a misleading connectivity suggestion. No target
change was observed in the independent report. Its failed conclusion must remain
attached to that baseline; broader successful tests do not override F01.

The report's unavailable real Supabase environment, external TLS and enterprise
proxy are unverified boundaries, not additional demonstrated product defects.
CI's real Supabase coverage remains separate from independent local acceptance.
Artifact-download, fixture-configuration, safe-delete and port-selection harness
interruptions described in that report do not justify product changes by themselves.
Existing acceptance files, database services and the report were preserved.

## Change and regression contract

- Archive parsing normalizes `EOFError` and decompressor `zlib.error`, alongside
  existing tar/IO/validation errors, into `ArchiveValidationError`. CLI still
  emits one JSON document, nonzero exit and `code: invalid_archive`.
- Gzip streams are read to EOF before a target can be opened. Tar's end markers
  alone do not require reading gzip's checksum/size trailer. Additional real
  subprocess checks showed the baseline accepting missing-trailer, wrong-CRC
  and wrong-size previews with exit 0; these now fail as invalid archives.
- The remaining stream is drained in bounded 1 MiB reads. This validates transport
  integrity, without promising archive-size limits or application-level integrity.
- Exception normalization is limited to archive reading/validation. The same
  exception types raised by a target backend remain `backend_error`; credentials
  and raw driver messages remain suppressed.
- Corrupt archives cannot open registry/storage/data factories, create a target
  HOME, or change an existing SQLite sentinel database. Valid archive preview and
  existing successful restore/migration behavior remain covered by regressions.

`tests/test_archive_integrity.py` covers eight malformed gzip variants, three
backend configurations and both CLI modes (48 combinations), a valid preview,
two real SQLite unchanged-database checks and two backend-error boundary checks.
These are pre-backend rejection tests; they do not claim live MySQL/PostgreSQL
connections. Real SQL restore compatibility is covered separately by CI.

## Reproduction and evidence

The original 100-byte archive was copied into this development task's private
ignored evidence directory, preserving its SHA-256:

`1efe2e10e0b4648bdc731947fe026e49347db6d2ec131f491591ee1ad7d46dc9`

Fresh task-owned HOME/config locations and credential-free environments were
used with the original installed wheel and the fixed development code. All six
original cases changed from `backend_error` to `invalid_archive`, exit 1, empty
stderr, without creating the target HOME. Three additional trailer previews
changed from exit 0/`ok` to exit 1/`invalid_archive`. Original acceptance resources
were read only; bytecode writes were disabled for the original environment.

Local evidence: `.artifacts/p1-f01/original-repro.json`, `cli-reproduction.json`,
`before.log` and `focused.log`/JUnit. Before the fix, the initial 51 new cases
produced 36 failures and 15 passes. Fixed targeted archive/portability/identity
regressions initially passed 132, with 38 unavailable-external-backend skips;
additional unchanged-database tests are included in the final full run.

```sh
python -m pytest tests/test_archive_integrity.py tests/test_portability.py \
  tests/test_restore_identity.py -q --timeout=45
```

The fixed commit needs a fresh matching CI wheel/sdist install outside the source
tree and replay of the copied original archive; version 0.9.8 alone does not identify
it. Retain `direct_url.json`, import/executable paths, artifact manifest and hashes.
Do not replace the independent baseline report with development-side pass claims.
External remote TLS, enterprise proxies, production-scale performance and the
independent report's real Supabase gap remain unchanged.
