# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.8.3] - 2026-08-18

An independent black-box audit of 0.8.2 filed reproducible counter-examples
against both of that release's headline claims: credentials could publish,
and blocked credentials could appear in the block message. The audit was
right on every count that mattered. **If you are on 0.8.2, upgrade.**

### Security

- **Credentials written the ordinary way are now detected.** Rules matched
  literal keywords, so common code shapes went straight through:
  `const password = "…"` (the table had `password=`), `const Authorization =
  "Bearer …"` (only `authorization:`), and `postgresql://` — which is what
  SQLAlchemy and Django write, while only `postgres://` was listed. Any DSN
  whose password contained `@ ! $` also escaped, because the character class
  stopped at the first `@`. Replaced with shape rules covering credential
  assignments (including variable declarations), bearer values, JWTs, cloud
  key prefixes, 17 DSN dialects, and a generic `scheme://user:pass@host`.
- **Secrets no longer reach the block message.** Two separate holes. A
  finding's context is a window cut out of the page, so `password=` could
  arrive at the masker already truncated to `word=`; because masking needed
  the whole keyword, a *neighbouring* finding's context kept its secret in
  the clear. Independently, long digit runs (national ID, phone, card) never
  matched a masking rule and printed in full. Masking is one function, used
  by the console, the stored scan history, and the LLM review path.
- **The placeholder exemption is no longer a bypass.** `REPLACE_MEsk-…` and
  `password=***RealSecret` published, because the exemption matched a prefix
  instead of the whole value. It now requires the placeholder to be the
  entire value; a known type prefix (`sk-`, `Bearer `) may precede it. Regex
  rules consult the exemption too — shape matching had made
  `secret_key = "REPLACE_ME"` a credential, and blocking documentation is
  what teaches people to waive the scan.

### Fixed

- `migrate-check` told the editor layer "republishing does NOT replace
  this". It does: publish re-injects the editor while the site is marked
  editable, so the tag comes back on its own and removing it from the HTML
  does not stick. Layers now declare `on_republish` as auto / flag / sticky
  instead of one boolean covering two questions. The old test had pinned the
  wrong wording.
- `import` left a registry row behind for a page it held back on a
  credential, producing a site that lists and resolves but serves nothing —
  indistinguishable from a storage fault, and it makes the slug look taken.
  Rolled back now, only for rows that run created.
- `publish --update` reset a site's data model to `default` when the source
  file carried no data layer, silently pointing the page at an empty table.
  It now inherits the model the live page is using.
- Three more registry reads were capped: the server index at 100 and the
  `_me` permissions endpoint at 1000, where an owner past that limit stops
  seeing their own sites.
- `init --no-serve` help text now says the self-check still binds loopback
  briefly, which is what it has always done.

### Added

- **Scan history** — every scan is recorded so `doctor` can tell a checked
  page from an unchecked one, and an unchanged page is not re-scanned.
  Findings are stored redacted through the same masker as the console.
  `security.scan_keep` caps records per site (default 20, `0` keeps all,
  env `GOLIVE_SCAN_KEEP`); pruning is per site, so a page published hundreds
  of times cannot evict another site's only record. A cached verdict is
  reused only when page and ruleset are both unchanged.
- Site manifests and per-site policies (storage layer only — no command
  reads them yet; the reporting lands in 0.9.0).
- The scanner regression corpus grew to 22 `must_block` / 14 `must_pass`
  samples, including every counter-example from the audit. Adding a case is
  adding a file under `tests/corpus/`. See
  [docs/security.md](docs/security.md#regression-corpus).

## [0.8.2] - 2026-08-18

A security pass over the publish path. The scan gate now separates
credentials from content warnings, and every route that writes HTML to
storage was traced and accounted for. Most of what follows was found by
building the test rather than by reading the code.

### Security

- **`--skip-scan` could publish a live credential.** One flag waived the
  entire scan, so a page carrying a private key, a database DSN or an API
  token published without complaint. The gate now separates two kinds of
  finding: credentials (private keys, DSNs, cloud keys, bearer tokens,
  `password=`, national ID numbers) **block regardless of any flag**, while
  content findings (salary, personal-information vocabulary) warn and
  publish as before, with the new `--skip-content-scan` to silence the
  warning. `--skip-scan` keeps working as
  an alias for the content waiver and prints a deprecation notice; it is not
  scheduled for removal.
- **The block message printed the secret it was blocking.** Findings go to
  stderr, CI logs and screenshots, so a blocked publish leaked the value it
  was protecting. Redaction was only shaped for digit runs and `key=value`;
  a DSN password (`://user:pw@host`) fell straight through, and one field
  truncated the match instead of masking it. All output now passes through a
  single redaction function.
- **A strong password escaped redaction precisely because it was strong.**
  The mask required the first two characters of a value to be alphanumeric,
  so `password=P@ssw0rd…` — punctuation in third position — was left intact
  while a weak all-letters password was masked correctly.
- **Five common token formats were not detected at all**: GitHub personal
  access tokens (`ghp_`/`gho_`/`ghs_` and fine-grained `github_pat_`), PyPI
  tokens, Slack tokens and Google API keys. A GitHub token in a page raised
  only a waivable content warning.
- **Restoring an archive skipped the scan entirely.** `golive import` wrote
  HTML straight to storage, so an archive from another machine could carry a
  credential onto a live page. Import now scans each page and holds back
  only the offending one — the rest of the restore proceeds, since import is
  not atomic and aborting midway is the worse outcome. Held-back pages are
  reported with the secret redacted, and the exit code is non-zero so a
  scripted restore cannot report success while pages are missing.
- **Setup documentation was blocked as if it were a leak.** `password=***`
  and `API_KEY=<your-key-here>` in a guide were treated as credentials.
  Blocking documentation is what teaches people to publish with the scan
  waived, which is how a real secret gets through later. Placeholder values
  (`***`, `$DB_PASSWORD`, `{{ token }}`, `REPLACE_ME`, entity-encoded
  `&lt;your-key-here&gt;`, empty values) are now exempt — but the
  placeholder must be the *entire* value: `password=xxxRealSecret` is a
  secret, not a placeholder, and still blocks.

### Fixed

- **`golive list` and `golive doctor` stopped at 200 sites**, and
  `/api/sites` reported that truncated figure as the total. `list_all(limit=N)`
  returns the first N rows rather than page N, so anyone past 200 sites saw a
  silently short list. All three now page through the registry.
- **`golive export` could pack the same site twice.** The paging helper
  accumulated each batch, but every larger request re-returned rows already
  seen; at exactly 500 sites the archive contained 1000 registry rows. Found
  by counting rows in a real export rather than trusting the helper.
- **`golive migrate-check` missed the inline editor and mislabelled
  everything else.** Detection inferred layers from hardcoded `<script>` id
  strings, one of which (`inline-editor-layer`) never existed — the real id
  is `golive-inline-editor`, so an editor layer went unreported. Watermark
  and editor layers were also advised that "republishing replaces this
  automatically", which is only true of data layers.
- **Injected layers now identify themselves.** Every injected `<script>`
  carries `data-golive-layer`, `data-golive-schema` and
  `data-golive-version`, and the layer list in `golive/inject/__init__.py`
  is the single source both injection and detection derive from. Detection
  falls back to the attribute when an id is unrecognised, so a layer from a
  newer or older release is still found.
- **Security rule categories were lost on the way to the scanner.** The
  `security_rules` table used one column for both rule shape and sensitivity
  category, so every stored rule reached the scanner as the same category and
  reported under the wrong label. Existing databases migrate transparently.

### Added

- **A scanner corpus** at `tests/corpus/`: 14 pages that must be refused and
  11 that must publish cleanly, walked at run time so adding a case means
  adding a file. The false-positive half matters as much as the other — a
  scanner that cries wolf gets routed around. Three of the security fixes
  above were found by running this corpus for the first time.
- A test that pins the number of `storage.publish()` call sites per module,
  so a new write path forces a deliberate decision about whether its HTML is
  trusted.

## [0.8.1] - 2026-08-17

### Fixed — Supabase, verified against a real project

v0.8.0's Supabase support had only ever run against an in-process fake
PostgREST server. A verification pass on an actual Supabase project found
six issues the fake could not surface.

- **Storage downloads mangled every non-ASCII byte.** The authenticated
  object endpoint answers `text/plain` with no charset, so `requests`
  assumed ISO-8859-1 and `resp.text` undid what upload had written as
  UTF-8. Pages served through golive showed mojibake while the public
  object URL looked fine — and `golive export` baked the damage into the
  archive, quietly corrupting the backup. Now decodes bytes as UTF-8
  explicitly, and names the object path if the content really is not UTF-8.
  Re-verified on a real project: browser, public URL, served page and
  archived HTML all hash identically.
- **Whole-archive import into an empty Supabase instance failed, and failed
  halfway.** The registry could not write an explicit `site_id`, and the
  error surfaced *after* data rows and HTML had been written — leaving
  orphan objects with no metadata pointing at them. Supabase needed no new
  machinery for this: its own `create()` already sets `site_id` explicitly.
  HTML is now written only for sites whose registry row actually landed.
- **`--on-conflict skip` overwrote HTML anyway**, letting an old archive
  clobber a newer live page. Skipped sites keep their HTML, and the summary
  reports how many were left alone.
- **`migrate --dry-run` reported a target row count it never measured.** It
  skipped opening a non-sqlite target and printed the initial `0`, so a
  Supabase table holding rows previewed as empty — which reads as "safe to
  migrate into". It now counts for real, reports `unknown` when the target
  cannot be reached, and refuses same-backend migrations outright instead of
  previewing a no-op.
- **The demo page claimed "no cloud, no API key" regardless of backend.**
  Published against Supabase that same page ships an anon key, so the claim
  was both wrong and an invitation to skip the RLS setup the mode depends
  on. It now describes the backend it was actually published against.
- **Generated SQL only mentioned RLS.** `GRANT` and RLS are separate gates,
  and newer Supabase projects no longer expose new tables to the Data API
  automatically, so policies alone still yield `401` / `42501`. Both tables
  now print the grant alongside the policies, and note that a missing
  SELECT policy shows up as an HTTP 200 empty array rather than an error.

### Documentation
- The Supabase chapter walks the four steps (config, keys, tables, verify)
  and says plainly why RLS is mandatory there and optional for the other
  two backends. Adds a GRANT-vs-RLS troubleshooting section.
- Notes that an archive carries no backend configuration: importing into a
  fresh `GOLIVE_HOME` restores to the defaults unless you put a
  `golive.yaml` there first.
- Notes that the remote-storage read cache is per-process, so publishing
  from another shell can take up to 60 s to appear in a running server.
- The self-hosted Postgres chapter was numbered `8a` while sitting after
  chapter 9, and was missing from the table of contents.

### Known limitations
- `golive import` is not atomic and does not retry. A transient network
  failure mid-import can leave data rows written without their registry
  entries; re-running the import after clearing the partial rows is safe.
  Retries are deliberately not added here until the write paths are
  measured for idempotency.

### Tests
- 13 regressions covering each fix above, every one confirmed to fail with
  its fix reverted. 859 total.

## [0.8.0] - 2026-08-16

### Added — data portability (export / import / migrate)

golive is a self-hosted tool, and "your data is yours" means data should
go in *and* come out. This release adds three commands that make full
backup, restore, and cross-backend migration first-class operations.

- **`golive export`** — produces a single tar.gz archive of the entire
  instance (sites, HTML, data rows). Archive structure: `manifest.json`
  (version, timestamps, backend labels, row counts), `registry.jsonl`
  (one site per line), `data.jsonl` (one data row per line),
  `sites/<site_id>.html`. Supports `--sites-only`, `--data-only`,
  `--site <ref>` for partial exports, and `-o` for a custom output path.
  Pagination is handled transparently: the export iterates through every
  site and every data row past `list_all`'s default 200-row cap and
  `list()`'s 20-row page, cross-checks final counts against the backend,
  and aborts rather than writing a silently incomplete archive.
- **`golive import`** — restores an archive produced by `golive export`.
  Three slug-conflict strategies (`skip` / `overwrite` / `rename`), all
  genuinely implemented. Idempotent: importing the same archive twice
  with `skip` produces no duplicates. `--dry-run` reports without
  writing. Path traversal in malicious archives is rejected (Python 3.12+
  `filter="data"` and manual validation for 3.9–3.11). Original site_ids
  are preserved so HTML files and cross-references stay intact.
- **`golive migrate <data|registry> --to <backend>`** — copies rows from
  the current backend to a target (sqlite / postgres / supabase). Source
  data is never deleted. Row counts verified before and after; mismatch
  aborts with "source X rows, target Y rows". Target backend
  unavailable (e.g. psycopg not installed) fails before touching anything
  with the exact fix command. `--dry-run` reports without connecting to
  the target.
- Admin portal data-backend page now shows the actual `golive migrate`
  command to run instead of a generic "data will not be migrated" message.

### Added — end-to-end self-check (`golive verify`)
- **`golive verify`**: really runs the full chain — starts a temporary server
  on a random port, requests `/health`, publishes a test page with TemplateAPI
  injection, inspects the injected script for correct mode and leaked secrets,
  writes → reads → deletes a data row, then cleans up. Designed so that
  "broken but doctor-green" (the 0.7.6 failure) is impossible to miss.
- `--keep` keeps the temporary test site for manual inspection.
- `--json` outputs machine-readable JSON for CI and issue templates.
- Supabase mode is handled correctly: verify explains that pages call
  Supabase directly and the local `/api/data` endpoint is not used —
  not a failure.
- Postgres mode without `GOLIVE_PG_DSN` or `psycopg` gives an actionable
  fix command instead of a cryptic error.
- Failed verify exits non-zero (CI-ready).

### Changed
- `golive doctor` success message now reads "Static checks passed. Run
  `golive verify` to test the data path end to end." — honest about what
  it actually checks.
- `golive init` ends with a one-line feedback hint pointing users to
  `golive verify` and the issue tracker.
- README quickstart condensed to a 30-second minimal example (EN + zh-CN).
- Bug report template now asks for `golive verify --json` output.
- Backup/restore now documented as working across all three backend
  families (sqlite / postgres / supabase), in any registry+data
  combination.

### Fixed
- **Export could write a short archive and call it a success.** The
  registry count check re-ran the same paginated helper and compared the
  result to itself, so it agreed even when pagination was the broken
  part. A simulated one-page truncation produced a 200-of-250 archive,
  printed "Exported" and exited 0 — with a manifest that also said 200,
  making the loss invisible from inside the archive. The check now
  compares against a `COUNT(*)` that bypasses pagination, and refuses to
  write the archive on mismatch. Verified with 250 sites / 137 rows:
  complete export, faithful round-trip, and an injected truncation aborts
  with exit 1 and no file on disk.
- **Re-importing on Supabase duplicated every data row.** The import's
  duplicate check was a raw SQL probe branching on `._conn` / `.dsn_env`;
  the Supabase store speaks PostgREST and has neither, so the check was
  dead code there and `skip` inserted the same rows again on every run
  while reporting them as successful imports (4 rows → 8 on the first
  re-import, compounding after that). It now goes through `list()`,
  which every data backend implements. Names are compared exactly,
  because `list(name_prefix=)` is a prefix match — importing `r1` no
  longer collides with an existing `r10`.
- Import no longer falls back to `create()` when preserving a site_id on
  an unrecognised registry backend. `create()` mints a fresh site_id
  while the archive stores HTML under the original, so the import would
  "succeed" with every restored page pointing at storage that does not
  exist. It now fails loudly.
- `golive verify`'s data round-trip goes over real HTTP instead of
  calling the request handler directly. The 0.7.6 outage broke the route
  guard *in front of* the handler, so a direct call would have reported
  green while every published page stayed broken.

### Removed
- `_safe_extract()`, which was never called — import reads archive
  members via `extractfile` and never writes to disk. Leaving it in
  implied a protection layer that no code path used.

## [0.7.7] - 2026-08-16

The Postgres backend from 0.7.6 worked in the CLI but not in the browser.
If you configured `data.backend: postgres` on 0.7.6, published pages could
not read or write — **upgrade before using Postgres**.

Verified end to end against PostgreSQL 16 in a real browser: page →
injected `TemplateAPI` → `/api/data` → JSONB row in the database.

### Fixed
- **Postgres now actually works for published pages.** 0.7.6 shipped working
  Postgres stores but the page path still refused them: `publish` reported
  "data.backend is none — injected a stub", the injected script fell back to
  supabase mode with an empty URL, and `/api/data` answered 404. Data backends
  are now classified by *shape* — server-proxied (`sqlite`, `postgres`, page
  calls the local `/api/data`, no credentials in the HTML) versus page-direct
  (`supabase`) — behind `factory.is_server_proxied_data()` /
  `data_backend_ready()`, and publish, injection, `/api/data` and the admin
  data API all consult that instead of hardcoding `== "sqlite"`. The injected
  `mode` is now `local` for both sqlite and postgres.
- The admin portal's data API (`/api/admin/data/*`) now serves Postgres.
- `migrate-check`, `context` and `doctor` no longer report a healthy Postgres
  backend as unconfigured or disabled. `doctor` reports the real Postgres
  table (`sites`, not Supabase's `golive_sites`), the DSN env var name,
  connection state, server version and row count — never the DSN itself.
- `registry.touch()` now always advances `updated_at`: timestamps moved from
  second to microsecond precision, so create-then-touch inside one second is
  no longer a no-op. Both registries changed together.
- Docs, `golive.example.yaml`, the bundled skill and `backends.md` agreed that
  Postgres either did not exist or was unfinished. All of them now document it
  consistently, including the two backend shapes.

### Tests
- Added `tests/test_data_layer_e2e.py`: walks config → publish readiness →
  injected script → HTTP `/api/data` → store for every server-proxied
  backend, which is the chain that had no coverage and let the 0.7.6 page
  breakage ship. Postgres cases skip without `GOLIVE_PG_DSN`.
- The Postgres suite no longer deletes `GOLIVE_PG_DSN` from the environment
  mid-run (it used `os.environ.pop` without restoring, which disarmed every
  integration test that followed and produced 45 misleading failures); it now
  uses `mock.patch.dict` and asserts the exact exception types and messages.
- Registry integration tests track created sites by id, so a test that renames
  its site no longer leaves rows behind in a shared database.

### Changed
- `golive skill install --force` now backs the old copy up to
  `$GOLIVE_HOME/backups/skills/` instead of leaving
  `html-golive.bak-<stamp>/` inside the agent's skills root, where a valid
  SKILL.md made agents list html-golive twice (once stale).
- **`publish` told Postgres users their data was in `$GOLIVE_HOME/data.db`.**
  Both server-proxied backends shared one hint that named the SQLite file, so
  people went looking for their rows in a database that stays empty. The hint
  now names the actual store and, for Postgres, the DSN environment variable
  (never the DSN itself).
- The data-layer guide, both READMEs and two bundled skill references still
  described only sqlite and supabase. `docs/data-layer.md` now has a Postgres
  setup section, and every `/api/data` reference covers both server-proxied
  backends. `docs/backends.md` marks Postgres as usable from 0.7.7, with a
  note that 0.7.6 must not be used for Postgres.

### Tests
- `tests/test_docs_mention_backends.py` — fails when a data-layer doc stops
  naming a shipped backend, or ties `/api/data` to sqlite alone. Docs drifted
  silently for a whole release; this makes it a test failure.
- `tests/test_version_consistency.py` — the package version, `pyproject.toml`,
  the bundled skill frontmatter, `/health` and the changelog must agree.
- Publish-hint regression tests assert the sqlite and postgres wording
  separately, and that no DSN component ever reaches stdout.

## [0.7.6] - 2026-08-14

### Added
- **Self-hosted Postgres backend** for the data and registry layers. Users
  with an intranet PostgreSQL instance can now skip Supabase and use a real
  database without cloud dependencies. Set `data.backend: postgres` and/or
  `registry.backend: postgres` in `golive.yaml`, install
  `pip install 'html-golive[postgres]'`, and set `GOLIVE_PG_DSN` to a
  libpq connection string. Tables auto-create on first use (same as
  SQLite); `content` is stored as JSONB; all public method signatures and
  return types are identical to the SQLite stores. `golive db init` now
  detects the postgres backend and connects accordingly.

### Fixed
- **CI reliability**: the test job could hang for the full GitHub timeout
  because the test OIDC server ran single-threaded with HTTP keep-alive; a
  lingering client connection would block the accept loop on a background
  thread. The fake IdP now serves threaded over HTTP/1.0, and CI runs pytest
  with a per-test timeout (`--timeout=45 --timeout-method=signal`) plus job
  timeouts so a stuck test fails fast instead of holding the runner.
- Two `ai_review` tests asserted Chinese wording and broke under CI's
  English default locale; they now pin `GOLIVE_LANG=en` so note assertions
  are locale-independent.

## [0.7.5] - 2026-08-07

This release is mostly about making golive usable by people who do not read
Chinese, plus signature verification for OIDC logins.

**Heads up:** the CLI now speaks English by default. Set `GOLIVE_LANG=zh`
to get Chinese back — see "Changed" below.

### Added
- **`id_token` signature verification for OIDC.** Tokens are now checked
  against the IdP's published signing keys before a session is created:
  the signature must verify, `iss` / `aud` / `exp` / `nonce` must match,
  and `alg: none` is refused. Requires `pip install 'html-golive[oidc]'`;
  without it golive refuses to start in OIDC mode rather than quietly
  skipping verification. Set `auth.oidc.verify_signature: false` to opt
  out, and the server will say so loudly at every startup.
- **Trusted reverse-proxy auth** (`auth.provider: proxy`) for setups where
  the application is not allowed to talk to the IdP directly. Requires an
  explicit `auth.proxy.trusted_ips` allowlist — golive will not start with
  an empty one, because anyone able to reach the port could otherwise
  forge the identity header.
- **Four new admin pages**: identity, data backend, security scanning and
  global settings. Each connection form has a test button that performs a
  real probe rather than validating the shape of what you typed.
- **Settings and security rules can now live in the database.** Values
  declared in `golive.yaml` remain read-only built-ins; anything added
  through the portal overrides them and survives `pip install -U`.
  Previously custom scan rules lived inside the installed package and were
  overwritten on upgrade.
- **A shareable address after publishing.** Where a page used to be
  advertised only as `localhost`, golive now also prints the LAN URL, and
  says when `--host 0.0.0.0` is needed for anyone else to reach it.
- **`GOLIVE_LANG`** to choose the CLI language explicitly.

### Changed
- **The CLI now defaults to English.** Chinese is used when `GOLIVE_LANG`
  says so or the system locale is unambiguously Chinese; otherwise English.
  If you parse golive's output in a script, check your matches — the text
  has changed. `GOLIVE_LANG=zh` restores the previous wording exactly.
- `golive init` treats a missing AI agent as "skipped" rather than a
  failure. Not having one installed is a normal setup, and the old red ✗
  read as breakage.

### Fixed
- **`server.public_base` was ignored when composing site URLs**, and a
  loopback bind never warned that the printed address was unreachable from
  other machines. Both settings were read from the wrong place in the
  config tree.
- Unknown top-level keys in `golive.yaml` are now reported at startup,
  naming the correct location for the common mistakes. Writing `admins:`
  at the top level instead of under `admin:` used to be silently ignored,
  leaving you logged in but without access.
- An `id_token` with no `exp` claim was accepted, and the clock-skew
  tolerance was wide enough to keep expired tokens alive for minutes.

## [0.7.2] - 2026-07-31

A macOS fix. If you are on macOS and `golive serve start` appeared to do
nothing — process alive, log empty, port never answering — this is why.

### Fixed
- **The server could hang on startup on macOS.** Python's
  `HTTPServer.server_bind` performs a reverse DNS lookup purely to fill
  in a field we use for logging; on macOS, resolving a name for
  127.0.0.1 can block until the resolver gives up. The process stayed
  alive, printed nothing at all, and never answered on its port — the
  hardest possible failure to read. Binding no longer waits on a
  resolver. The same fix is applied to the preview server.
- Outbound "what is my LAN address" probes are now bounded by a timeout.
  They exist only to print a friendlier URL and must never delay
  startup.
- `golive serve start` quotes the tail of the server log when startup
  times out, instead of only pointing at a file.
- A path assertion in the test suite compared strings rather than
  resolved paths, so it failed on macOS where `/var` resolves to
  `/private/var`.

### Tests
- 565 → 572. CI passes on macOS.

## [0.7.1] - 2026-07-30

Getting started should take two minutes, not an afternoon. Everything in
this release comes from watching someone install 0.7.0 for the first time.

### Added
- **`golive init`** — one command from nothing to three working URLs. It
  picks a data directory, checks the environment, installs the agent
  skill, sets up the data layer, publishes two demo pages, starts the
  server, and then actually verifies over HTTP that all of it works
  before telling you it succeeded. Re-running it is safe: existing sites
  and data are left alone. Add `--background` to keep the server up after
  you close the terminal.
- **`golive context`** — shows which configuration is actually in effect
  and *where each value came from* (`$GOLIVE_HOME`, a pointer file, or a
  default). This is the answer to "I published a site but `golive list`
  shows nothing": the CLI and the server were reading different homes.
- **`golive demo install`** — a static intro page and a working to-do
  list backed by the SQLite data layer, so you can confirm persistence
  yourself: add an item, refresh, it is still there.
- **`golive serve start | status | stop | restart | logs`** — run the
  server in the background instead of holding a terminal open. Bare
  `golive serve` still runs in the foreground exactly as before.
- **`docs/upgrading.md`** — upgrade paths for PyPI and git users,
  including recovery steps for the v0.7.0 history rewrite.

### Changed
- **The agent skill installer now recognises Codex and Cursor**, and
  detects agents by their own directory rather than requiring a
  `skills/` folder to already exist — a freshly installed Codex has
  `~/.codex/` but no `~/.codex/skills/`, so it used to be skipped
  entirely and the skill landed somewhere the agent never reads. When
  several agents are present you get to choose; `--list-targets` shows
  what was found without installing anything.
- **`golive doctor` is now the one place to verify an installation**: CLI
  version, running server version (and a warning when they differ, which
  is what happens when you upgrade but forget to restart), all three
  backends with real paths and sizes, skill status, and the portal URL.
  It also finds the server on whatever port it is actually running on
  instead of assuming the default.
- **`/health` reports version, home, data backend and pid**, which is
  what makes the version check above possible.

### Fixed
- `golive init` used to print three URLs and then take the server down
  with it when the command exited, leaving the user with three dead
  links.
- Hostname resolution and path comparison in the test suite no longer
  fail on macOS, and CI now runs there.

## [0.7.0] - 2026-07-30

Zero-config data layer, an agent skill in the box, permission management,
and a bilingual themeable portal.

### Added
- **SQLite data backend, now the default.** `window.TemplateAPI` works
  out of the box with no cloud account: rows live in
  `GOLIVE_HOME/data.db` and pages reach them through a PostgREST-shaped
  `/api/data/<table>` endpoint served by `golive serve`. Supabase
  remains available and unchanged; `data.backend: none` still disables
  the layer entirely. Note that sqlite-backed pages must be opened
  through `golive serve` — a `file://` copy has no server to talk to.
- **An agent skill shipped inside the package**, plus
  `golive skill install | status | path`. The installer detects common
  agent skill directories, works offline from the bundled copy, can
  pull the latest from GitHub with `--from-github`, backs up an existing
  copy on `--force`, and reports version drift against the running
  golive. The skill teaches an assistant to probe the environment with
  `golive doctor` before acting, and states plainly that golive is
  self-hosted and unrelated to any similarly named hosted or internal
  tool.
- **Permission management** — `/api/admin/permissions` with dual-source
  superadmins: entries from `admin.admins` / `GOLIVE_ADMINS` are builtin
  and cannot be deleted through the API (you can't lock yourself out),
  while database-backed admins can be added and removed at runtime.
  Bulk grant/revoke of maintainers across many sites reports applied,
  skipped and failed slugs separately. New portal page renders all of
  it; every write is audited.
- **Light and dark portal themes** with a follow-system option,
  persisted per browser and applied before first paint.
- **Bilingual portal** (English / 中文), 138 translation keys with a
  test asserting both dictionaries stay in sync.
- **"Copy for your AI assistant" buttons** on setup screens. Instead of
  handing you a yaml snippet to apply by hand, they copy a complete task
  description — your real `GOLIVE_HOME`, the config path, the steps,
  how to handle secrets, how to verify, and a documentation link — ready
  to paste into an AI assistant.
- **Chinese landing page** at `docs/index.zh.html` with two-way language
  switching.

### Security
- `golive serve` now warns loudly at startup when the unauthenticated
  in-page data API is bound to a routable address without a token or
  OIDC configured. The data layer is deliberately open (the browser
  calls it directly, like an embedded anon key) — this makes the
  trade-off visible instead of surprising. Table access stays restricted
  to the configured data table; the registry and SQLite metadata are not
  reachable.

### Fixed
- Documentation described a "local SQLite data layer" that did not
  exist — the three backend layers (storage / registry / data) are now
  described separately, and the sqlite data layer is real.
- Portal contrast fixes for WCAG AA on both themes, a CSS lock icon
  replacing an emoji that rendered as tofu on machines without an emoji
  font, and assorted spacing and alignment corrections found during
  visual review.

### Tests
- 232 → 413.

## [0.6.0] - 2026-07-27

Data management in the admin portal + audit rotation (M6).

### Added
- **Data management tab in `/admin`** (superadmin only) — manage the
  TemplateAPI rows (`golive_templates`) shared by all sites when a
  Supabase/PostgREST data backend is configured: model dropdown with row
  counts, paged row table with JSON-content search, formatted view
  dialog, JSON-validated edit, add row, delete with confirm. Shows setup
  guidance instead of an error when no data backend is configured.
- **Admin data JSON API** — `GET /api/admin/data/models`,
  `GET/POST /api/admin/data/rows`, `PATCH/DELETE
  /api/admin/data/rows/<id>`. Superadmin only; `400` with a hint when no
  data backend is configured; every write audited as
  `data.create`/`data.update`/`data.delete`.
- **TemplateStore helpers** — `list_models()` (distinct model_code +
  counts) and `search()` (paged rows with best-effort case-insensitive
  containment filter over name/description/content).
- **Audit log rotation** — before each write, `audit.log` over
  `admin.audit_max_bytes` (default 10 MB, env `GOLIVE_AUDIT_MAX_BYTES`,
  0 = off) rotates to `audit.log.1`, older archives shift up, keeping
  `admin.audit_keep` generations (default 5, env `GOLIVE_AUDIT_KEEP`).
  Rotation failures never block the write; `GET /api/admin/audit` reads
  only the current file.
- **CI badge** on both READMEs.

### Tests
- 33 new tests (199 → 232): data endpoints (models/pagination/search/
  CRUD/audit/403/401/no-backend-400/malicious model names), store
  helpers, audit rotation (threshold, keep-limit, shift-up, disable,
  fail-open rename, env-beats-yaml), portal data-view DOM +
  superadmin-only nav.

## [0.5.0] - 2026-07-26

Admin portal (M5): web-based operations console for `golive serve`.

### Added
- **Admin portal at `/admin`** — self-contained single-page console
  (no external CDN/frameworks; works airgapped): site list with
  search/pagination, detail drawer with metadata editing, maintainer
  tag management, ownership transfer (double confirm), snapshot list
  with one-click rollback, and delete gated on typing the slug.
  Superadmins additionally get a stats dashboard (total sites/bytes,
  7-day activity, top-10 by size) and a filterable audit-log view.
- **Admin JSON API under `/api/admin/*`** — `me`, `sites` (list/detail/
  PATCH/DELETE), `transfer`, `maintainers` (POST/DELETE), `rollback`,
  `stats`, `audit`. Unauthenticated → 401, insufficient role → 403;
  destructive delete requires `{"confirm": "<slug>"}`.
- **Role model** (`golive/server/authz.py`): `superadmin` (email in
  `admin.admins` yaml list or `GOLIVE_ADMINS` env — env wins; static
  token auth also counts, the token is operator-held), `owner`
  (registry column), `maintainer` (M3 list). Zero-config loopback
  callers keep working as before (treated as operator).
- **Admin audit trail** (`golive/core/audit.py`): JSONL at
  `GOLIVE_HOME/audit.log` — who/action/slug/ts/detail for every admin
  write and every online-editor save; served by `GET /api/admin/audit`
  with slug/action filters + pagination.
- **`golive admin open`** CLI + the serve banner now prints the portal
  URL.
- `admin:` section in `golive.example.yaml`.

### Changed
- SQLite registry now migrates an `owner` column into pre-v0.2
  databases transparently (older DBs created before the column existed).
- `serve` gained `PATCH`/`DELETE` HTTP method handling (admin API only).

### Tests
- 45 new tests (199 total): permission matrix per endpoint (owner /
  maintainer / superadmin / outsider), transfer revokes the old owner,
  delete confirm gate, audit recording/filtering/malformed-line
  tolerance, portal DOM/no-CDN/XSS-escape checks, HTTP identity
  resolution, and the owner-column migration.

## [0.4.1] - 2026-07-26

Security hardening + release infrastructure (M1-M4 retrospective fixes).

### Security
- **`GET /api/sites` no longer serves unauthenticated remote callers.**
  With no auth configured, the registry listing (site ids, slugs, names)
  is now only returned to loopback clients; remote callers must present
  a `GOLIVE_TOKEN` bearer token or an OIDC session. Previously any host
  that could reach the port could enumerate all sites.
- **`golive serve` now binds `127.0.0.1` by default** (was `0.0.0.0`),
  matching `golive preview`. Expose deliberately with `--host 0.0.0.0`
  or `server.host` in golive.yaml — the startup banner reminds you to
  pair that with auth.

### Added
- **GitHub Actions CI**: pytest matrix (3.9/3.11/3.12), compileall,
  wheel build with content verification (19 css styles + rules.yaml,
  no pycache), and an install-from-wheel smoke test.

### Changed
- **Published to PyPI**: `pip install html-golive` now works. (Install
  instructions briefly pointed at GitHub while the package was
  unpublished.)

## [0.4.0] - 2026-07-26

Docs, identity presets, and editor polish.

### Added
- **OIDC provider presets** (`golive/backends/auth/presets.py`): set
  `auth.oidc.preset: google | auth0 | okta | azure | keycloak | authentik`
  to auto-fill the issuer template and default scopes — supply only
  `client_id` and the secret env. `auth0`/`okta` take `domain:`, `azure`
  takes `tenant:`. Explicit `auth.oidc.*` fields always override a preset;
  presets contain only public, non-secret values.
- **Editor image upload button**: the online editor toolbar now has a
  🖼 image button that uploads via `POST /api/sites/<slug>/upload` (raw
  body + `X-Filename`), inserting the returned URL at the cursor. When no
  image host is configured (HTTP 501) it gracefully inlines the image as a
  data URL instead.
- **Full user manual** (`docs/manual.md`): a task-oriented guide covering
  all features (publishing, personalisation, styles, cloning, editor,
  access control, data layer, Supabase, doctor, logs, security, sharing,
  backends, identity, migration, FAQ), linked from both READMEs.

### Changed
- **Persistent cookie secret**: when neither `auth.oidc.cookie_secret` nor
  `GOLIVE_COOKIE_SECRET` is set, the OIDC session-signing key is now
  generated once and persisted to `GOLIVE_HOME/.cookie_secret` (mode 0600)
  so sessions survive a restart. Falls back to an ephemeral key with a
  warning only if the home dir is unwritable. (Closes M3 WARN #1.)

## [0.3.0] - 2026-07-25

M3 "editing & identity" milestone.

### Added
- **Online inline editor** (`golive/inject/editor.py` +
  `golive/server/editor_api.py`): per-site opt-in via
  `golive publish --enable-editor`. Floating ✏️ button → contenteditable
  text editing → save through `PUT /api/sites/<slug>/content` with
  Bearer editor token + `X-Editor-User` (URL params stashed in
  sessionStorage; OIDC sessions accepted too). Unsaved-changes guard,
  status toasts, auto-reload after save.
  - Server side: constant-time token compare, per-site `editable` gate,
    **owner/maintainer ACL**, 10 MB body limit, `text/html` content type
    required, snapshot before every overwrite (rollback covers
    conflicts), audit-log entry per save.
  - **The save channel re-runs the full publish security pipeline**
    (code-safety checker + rule/AI scanner) — editing can never bypass
    the scan.
  - Registry schema: `sites.editable` BOOLEAN + `sites.maintainers`
    JSON (SQLite migrates in place; Supabase DDL includes upgrade
    hints). New CLI: `golive maintainer add|remove|list <site> [email]`.
  - Shared-token mode (no owner/maintainer set) triggers an explicit
    warning at `--enable-editor` time.
- **Watermark layer** (`golive/inject/watermark.py`): canvas-tiled
  diagonal identity watermark. Identity sources in priority order:
  OIDC current user (email prefix only — never the full address),
  static text (`watermark.text` / `GOLIVE_WATERMARK_TEXT` /
  `--watermark <text>`), or `<meta name="golive-watermark">`.
  Inline JS by default; `watermark.cdn_url` switches to your own CDN.
  Style knobs: opacity / font_size / rotation / color. Optional
  `watermark.report_webhook` (POST `{slug,user,ua,ts}`) — no telemetry
  by default. `GOLIVE_WATERMARK_OFF=1` kill switch (also strips
  previously injected layers on republish).
- **LLM security review** (`golive/security/ai_review.py`): weak scan
  hits get an optional semantic second pass through any
  OpenAI-compatible Chat Completions endpoint
  (`security.llm.base_url/api_key_env/model/timeout`). Policies:
  unconfigured → skip (rule verdicts stand); `strict_mode: true` +
  unconfigured → publish refused; LLM `sensitive:false` → hit cleared;
  `sensitive:true` → kept; timeout/error/junk → conservative keep.
  Only masked hit contexts are sent (never whole HTML), fenced as JSON
  with a prompt-injection guard. Strong hits always block without an
  LLM call. Compatible with OpenAI / Azure / Ollama / OneAPI / vLLM.
- **Generic OIDC AuthProvider** (`golive/backends/auth/oauth.py`):
  `auth.provider: oidc` with discovery-document auto-configuration.
  Authorization-code flow with **PKCE (S256)** and single-use,
  TTL-bound `state`; userinfo endpoint (id_token claims fallback);
  HMAC-signed session-id cookies (HttpOnly, SameSite=Lax, Secure on
  https or `force_secure_cookie`); in-memory session store with TTL.
  New server routes: `/auth/login`, `/auth/callback`, `/auth/logout`
  (with optional IdP end_session redirect), `/auth/me`. `/api/sites`
  and the editor API accept sessions alongside Bearer tokens.
  Example configs for Google / Keycloak / Dex-bridged GitHub in
  `golive.example.yaml`.
- Shared XSS escaping util `golive/inject/_escape.py` — template_api /
  supabase_api / editor / watermark all import the same
  `json_for_script` / `safe_comment` (one fix, four injectors).
- 68 new tests (129 total): editor ACL + HTTP e2e, watermark identity
  sources & kill switch, mock-LLM policy branches, fake-IdP OAuth flow
  with state/PKCE/cookie tampering, M2 WARN regression tests.

### Fixed
- S3 storage error handling now uses botocore's official
  `ClientError.response['Error']['Code']` (NoSuchKey / 404 / NotFound /
  NoSuchBucket → `FileNotFoundError`, AccessDenied →
  `PermissionError`) instead of substring-matching `str(e)` — an error
  *message* containing "404" no longer masks a real failure.
- Supabase Storage snapshot pruning is now guarded by an advisory
  lockfile (`<site_id>/.prune.lock`, pid+ts payload, 60 s TTL);
  concurrent publishers skip the prune instead of racing on deletes.

## [0.2.0] - 2026-07-25

M2 "data layer" milestone.

### Added
- **Config loader** (`golive/config.py`): `golive.yaml` is now fully
  effective. Lookup order `--config` → `$GOLIVE_CONFIG` → `./golive.yaml`
  → `$GOLIVE_HOME/golive.yaml`; missing file = zero-config defaults;
  env vars always override yaml (12-factor). Secrets stay in env —
  yaml stores `*_env` variable names.
- **Supabase backends** — one Supabase project can host all three layers:
  - registry: `golive_sites` table via PostgREST
    (`golive/backends/registry/supabase_store.py`)
  - storage: site HTML + snapshots in a Storage bucket with a 60 s
    read cache (`golive/backends/storage/supabase_store.py`)
  - data: `golive_templates` table + Python-side `TemplateStore`
    (`golive/backends/data/supabase.py`)
  - shared minimal PostgREST client (`golive/backends/postgrest.py`)
- **S3-compatible backends** (optional extra `pip install
  'html-golive[s3]'`): site storage (`backends/storage/s3.py`) and
  native image uploader with content-hash keys
  (`backends/images/s3.py`). Works with MinIO / COS / OSS / TOS / AWS.
- **JS data-layer injection** (`golive/inject/`): publish now detects
  `TemplateAPI` / `SupabaseAPI` usage and injects
  `window.TemplateAPI` / `window.SupabaseAPI` with signatures
  compatible with the original deployment contract (list / listAll /
  get / create / update / delete / sort / upsert; init / getUser /
  isReady / onReady / logout / query / insert / update / delete).
  Multi-modelCode support, placeholder hard-block, ready events,
  `{total, list}` / `{rows, count}` envelopes preserved. Without a
  configured backend a stub is injected (clear console errors, publish
  never blocked). New publish flag `--data-model`.
- **`golive migrate-check <file>`**: scans HTML for intranet-specific
  references (hard-coded internal hosts, leftover data-layer script
  blocks, data API call statistics) with file:line + advice report.
- **`golive db init --print-sql`**: prints `golive_sites` +
  `golive_templates` schemas with example RLS policies.
- **`golive data <list|get|create|update|delete|upsert>`**: server-side
  CLI twin of TemplateAPI.
- **Docker**: real `Dockerfile` + `docker-compose.yml` (golive serve +
  optional `--profile minio` local S3 stack with bucket bootstrap).
- Backend factory (`golive/backends/factory.py`) — CLI/server pick
  storage/registry/data implementations from config.
- Docs: `docs/data-layer.md` (API reference + examples + RLS warnings),
  `docs/migrate-from-intranet.md`, expanded `docs/backends.md` with
  three worked backend combos; bilingual README updates.
- Tests: config priority suite, in-process fake PostgREST server with
  registry/data CRUD round-trips, injection signature-parity assertions
  (method lists hard-coded from the upstream contract), migrate-check
  fixtures built from fragments at runtime.

### Changed
- `get_uploader()` selection order: env `GOLIVE_UPLOADER_CMD` → yaml
  `uploader.command` → yaml `uploader.s3.bucket` → none (base64).
- `golive.example.yaml` rewritten as a fully working annotated config.

## [0.1.1] - 2026-07-25

### Added
- 8 more built-in CSS styles — newspaper, bloomberg, ink, steampunk,
  palace, cyberpunk, xhs, xhs-fun — bringing the total to 19. Web fonts
  are loaded from Google Fonts (CSS2 API).
- `GOLIVE_FONT_CDN_BASE` env / `style.font_cdn_base` config: swap the
  `fonts.googleapis.com` prefix for a custom font mirror at injection
  time (e.g. `fonts.loli.net` or a self-hosted service).
- `golive preview --host` flag; preview now binds `127.0.0.1` by
  default (use `--host 0.0.0.0` for remote/container environments).
- README "Network behavior" section documenting every outbound call,
  plus the optional `FIRECRAWL_API_KEY` fallback for `golive clone`.
- Custom image uploader: `GOLIVE_UPLOADER_CMD` env /
  `uploader.command` config runs any CLI (`mytool upload {file}`) to
  upload bundled images and reference the returned URL; failures fall
  back to base64 inlining so publishes never break. Native S3 uploader
  reserved for M2.

### Fixed
- `from __future__ import annotations` added to modules using PEP 604
  unions, restoring the documented Python 3.9 compatibility.
- tar.gz extraction now guards against path-traversal members
  (`filter="data"` on Python ≥ 3.12, manual check on older versions).
- Preview panel style labels are now sourced from the canonical
  `STYLE_MAP` (new styles show up automatically).

## [0.1.0] - 2026-07-25

First public release — "M1 core": zero-config single-machine deployment.

### Added
- `golive publish <file|dir|zip>` — publish a single HTML file, a project
  directory (bundled into one HTML with all assets inlined) or a zip/tar.gz
  archive.
- Local-fs storage backend (`$GOLIVE_HOME/sites/`) with automatic snapshots
  (up to 10 per site) and `golive rollback` (dry-run + `--yes`).
- SQLite registry backend (`registry.db`): site id (uuid4 hex), name, unique
  slug, timestamps, owner, notes.
- Built-in HTTP server `golive serve`: `GET /<slug>`, `GET /s/<site_id>`,
  `GET /api/sites` (token-protected via `GOLIVE_TOKEN`), `GET /health`,
  simple site index at `/`.
- Short-slug validation: format check, built-in reserved words (variant-proof
  normalization) and registry collision check.
- Rule-based security scanner with built-in `rules.yaml` (credentials,
  private keys, connection strings, PII); strong hits block publish,
  `--skip-scan` bypass, user-extensible rule files.
- 11 built-in CSS beautification styles (`--style`, `golive styles`).
- Base64 image compression (`--compress`, optional Pillow extra).
- Website cloning `golive clone <url>`: URL classification, fetching with
  resource inlining, migration analysis, font-mirror patching,
  sensitive-config scrubbing, optional headless-Chrome rendering.
- Live preview `golive preview` with hot reload and style-switch panel.
- `golive doctor` environment health check.
- AuthProvider interface with `none` (default) and static-token providers.

### Notes
- Data layer (TemplateAPI/SupabaseAPI), S3 storage, Docker Compose land in M2.
- In-browser editor, watermarking, LLM security review and OAuth land in M3.
