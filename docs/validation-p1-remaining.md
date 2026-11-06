# P1 data, automation and environment validation

Development scope: [#13](https://github.com/Songhonglei/html-golive/issues/13),
stacked on the DATA-01 implementation in [PR #12](https://github.com/Songhonglei/html-golive/pull/12).
This is candidate 0.9.8 development, without publication or business deployment.
An identical version string does not identify an identical artifact.

## Contract changes

- SQLite/PostgreSQL/MySQL discover models using complete `GROUP BY` counts and
  perform literal substring filtering, counting and paging in SQL. Search covers
  name, description and serialized JSON content, including Unicode and literal
  `%`, `_`, `!`. Legacy `scan_limit` arguments remain callable without truncation.
- Supabase discovers all models by bounded pages, advancing by the number of rows
  actually returned when PostgREST caps a response. Generic JSON search remains a
  complete Python fallback, O(N) network/CPU work with bounded page memory. It is
  not an indexed search or a production latency guarantee.
- Default ordering is `sort_index DESC, created_at DESC, id ASC`; the unique ID
  breaks ties for unchanged datasets. Pagination is not a transaction snapshot
  and cannot prevent concurrent updates from moving rows between pages.
- Missing exact counts fail explicitly instead of becoming a fabricated zero or
  page-length total. Exports compare collected rows to independent table counts,
  including legacy records with an empty model namespace. Pause all writers:
  count equality cannot detect same-count edits or prove a consistent snapshot.
- Explicit `--json` mode captures a complete result before writing stdout.
  Parser errors exit 2, operation/configuration failures exit nonzero, interruption
  exits 130; help still exits 0 with help text. Failure codes include
  `invalid_arguments`, `invalid_config`, `invalid_input`, `conflict`,
  `backend_timeout`, `backend_unavailable`, `backend_error`, `invalid_output`,
  `interrupted`. Existing successful list/get shapes remain unchanged.
  `write_state: "unknown"` means a mutation may have committed: read independently
  before retrying. Exception text, partial stdout and private input are suppressed;
  failure reports redact known environment/config credentials.
- Docker sandbox control checks immutable container ID, a random ownership label
  and canonical directory label. A mismatched/unreachable daemon preserves
  resources. Missing containers can be cleaned without signalling a replacement;
  cleanup removes only the owned container and its anonymous volumes. Existing
  unlabelled containers are refused. Logs and credentials stay private. Docker
  stores data in its owned anonymous volume, so Linux's container mysql UID
  never needs access to the host's 0700 credential directory.

## Reproduction

Use a new HOME and dedicated tables/databases. Never reuse an acceptance or
business database. Install the exact artifact with dev/SQL/browser dependencies;
copy tests from its matching sdist and run outside the development checkout.
Retain commit, wheel SHA-256, import/executable paths and `direct_url.json`.

```sh
python -m pytest tests/test_cli_json_contract.py tests/test_large_data_contract.py -q
# Load dedicated GOLIVE_PG_DSN or GOLIVE_MYSQL_DSN privately to run real SQL cases.
GOLIVE_TEST_DOCKER=1 python -m pytest tests/test_sandbox_environment.py \
  tests/test_proxy_tls_environment.py -q --timeout=300 -o junit_family=legacy
GOLIVE_TEST_BROWSER_CHANNEL=chrome python -m pytest tests/test_browser_count_contract.py -q
# Or use installed Chromium and GOLIVE_TEST_BROWSER_CHANNEL=chromium.
golive verify --full --browser-channel chrome --json --report-dir <new-private-report>
```

Docker tests create only labelled random containers, use `mysql:8.4.13`, exercise
stop/repeat-stop/restart/persistence/cleanup, reject a mutated identity and an
existing directory, and exercise occupied ports, missing images and an unreachable
daemon socket. TLS tests issue a private short-lived CA and localhost certificate,
prove a nonempty MySQL `Ssl_cipher`, and require wrong-host/untrusted-CA failures.
Proxy tests run real HTTP forwarding and HTTPS CONNECT on isolated sockets,
verify environment inheritance/CA rejection and a structured timeout failure.
They do not change system proxy, daemon settings or certificate validation.

## Coverage matrix

`passed` below describes the named scope only. CI results and installed artifact
receipts follow below. Earlier DATA-01 recovery evidence
remains in [its report](validation-data01.md), not reclassified as new coverage.

| Scenario | SQLite | PostgreSQL | MySQL | Supabase |
| --- | --- | --- | --- | --- |
| 12,050 rows: exact models, late search, literal wildcards, stable tied pages, complete export | passed locally | passed, native dedicated DB | passed, dedicated Docker DB | passed with fake HTTP and real PostgREST CI |
| CLI JSON parser/config/partial output, conflicts, retry and interruption | passed locally; shared CLI contract | shared CLI + live SQL contracts passed | shared CLI + live SQL contracts passed | shared CLI + fake HTTP; live CI passed |
| Missing PostgREST total / server page cap | shared adapter guards | shared adapter guards | shared adapter guards | fake capped HTTP and real capped CI passed |
| Real browser count failure/default ID order | passed in Chrome against injected TemplateAPI fixture | shared browser contract only | shared browser contract; full mode separately | fixture only; no full Supabase browser claim |
| Full installed Chrome CLI/browser/SQL/restart mode | not rerun in this batch; prior DATA-01 passed | passed, 16 stages | passed, 16 stages | unsupported by full mode; not claimed |
| Docker lifecycle / TLS CA and hostname | not applicable | not applicable | passed, controlled loopback Docker endpoint | not applicable |
| HTTP proxy / HTTPS CONNECT / timeout | shared real HTTP client test passed | not a PostgreSQL proxy test | not a MySQL wire-proxy test | shared PostgREST HTTP client passed, controlled origin |
| External-network remote TLS, enterprise proxy / TLS interception | unverified | unverified | unverified | unverified |
| Multi-million rows, concurrent writers, production latency/RSS SLA | unverified | unverified | unverified | unverified |

CI adds an environment acceptance job and rejects skipped live environment tests.
SQL jobs run the large-data/CLI contracts; the Supabase job requires eight real
PostgREST scenarios, including the capped 12,050-row dataset. These are independent
of the normal unit matrix and browser/full acceptance. A missing browser or a
failed supported scenario is a failure, not an overall success.

## Local measurements and evidence

The dataset has 11,000 `large`, 1,000 `late_model`, and 50 legacy empty-model rows.
The search target is beyond row 10,000. Before/after SQLite used the same freshly
seeded table and previous source `0ff1077b3d7f6c19bcba5d2cd9761e5c0c588f85`:

| Measurement | Previous source | Current source |
| --- | --- | --- |
| Named model counts | `large=9950`; late model absent | `large=11000`, `late_model=1000` |
| Late needle search total | 0 | 1 |
| Model discovery + search wall time | 25.2 ms | 15.7 ms |
| Python allocations peak during queries | 944,322 bytes | 5,894 bytes |

This is one warm local sample using `tracemalloc`, not process RSS, a benchmark
suite or an SLA. SQL LIKE still scans matching model rows without a text index.
PostgreSQL/MySQL timing is retained in JUnit properties; comparisons on a shared
machine are descriptive only. Local evidence lives in the private ignored
`.artifacts/p1-remaining/` directory: full-suite logs, real DB JUnit, Docker/TLS
and proxy JUnit, Chrome results and `large-data-baseline.json`. Failed preliminary
runs remain available alongside corrected reruns. No credentials are committed.

Local source receipt (2026-11-03): 1269 passed, 133 skipped and 643 subtests
passed in the full suite. Real PostgreSQL and MySQL focused runs each passed
111 with 26 skips for the other absent external DSN; three large datasets ran
in each process (SQLite, fake PostgREST, and the named real SQL backend).
Docker/TLS/proxy acceptance passed all 11, without skips. Chrome's focused
injected-API count/order contract passed one. CI and installed-artifact results
must be attached to the exact commit before release acceptance.

## CI and installed-artifact receipt

Runtime/package baseline: `44a8be4baf52900a12362ed24a09f19bd1d23105`.
Linux-specific sandbox correction: `a54374a26392879991afa9a6507b2bf678e62b08`.
The first Linux environment job failed on readiness with the private host bind.
The correction uses the image's owned anonymous volume instead; its Linux
environment job passed. The failed run remains part of the evidence history.

The corrected [CI run](https://github.com/Songhonglei/html-golive/actions/runs/41629384149)
builds wheel/sdist/Skill with a source-commit manifest. Real Supabase CI passed
eight scenarios plus all six directed migration pairs (14 total); the 12,050-row
case exercises the real server response cap. SQL, browser/full and environment
jobs passed. All nine checks passed at this corrected runtime baseline,
including Python 3.9/3.11/3.12 and macOS.

The standard CI artifact was downloaded through the connected GitHub account;
ZIP and per-file SHA-256 values were checked before installation. A fresh Python
3.12 environment outside the repository contained the installed wheel and only
matching sdist tests/scripts (no source `golive/` directory). Import paths,
`direct_url.json`, runtime file hashes and environment isolation were recorded.

- Initial wheel SHA-256: `f9f99fd155ab31f4ff844b5db3edec9ee6fb47ded2c606823a33dfbed74be656`.
- Corrected wheel SHA-256: `a3b974b25a49b0700448191f0cb8b968280b3636db963a699010e81430efa412`.
- All 122 files under the wheels' `golive/` package were byte-identical; the
  correction changes the sdist sandbox/test resources and documentation. The
  corrected wheel was then installed and its matching sdist sandbox script
  independently compared with the corrected development source.
- Installed real PostgreSQL: 111 passed, 26 skipped; full Chrome mode 16/16.
- Installed real MySQL: 111 passed, 26 skipped; full Chrome mode 16/16.

The corrected installed artifact additionally passed all 34 focused JSON,
Docker/TLS/proxy and real Chrome count/order checks. A first isolated-HOME smoke
correctly failed to find the Docker daemon; the rerun explicitly selected the
authorized daemon socket without copying user credentials. With an isolated
HOME, supply an explicit `DOCKER_HOST` when Docker relies on a per-user context.
Both failed preliminary receipts are retained.

Each 26-skip set is for the other external SQL backend not configured in that
process. Full reports include direct SQL, temporary service PID/HOME and
restart persistence; both runs cleaned their own random pages/data/server.
The explicit matrix still excludes external-network TLS, enterprise proxies,
Supabase full browser/restart mode and production-scale performance guarantees.

All newly created native PostgreSQL and Docker MySQL instances were stopped and
their dedicated data directories/credentials and owned anonymous volumes removed.
Existing unrelated containers, services, databases and the pre-existing untracked
build directory were preserved. The installed venv and private evidence remain
for review; no merge, release or business deployment was performed.

## Independent acceptance follow-up: F01

Independent acceptance of `b7e89ab` found a genuine invalid-archive classification
failure despite the prior green CI: a 100-byte truncated gzip produced
`backend_error`. That baseline remains failed for F01. The follow-up normalizes
compressed-reader exceptions and requires complete gzip trailer validation before
opening any target; missing-trailer/CRC/size previews are also rejected. See
[F01 review and reproduction](validation-f01.md). External environment gaps remain
unverified; the independent report and its existing resources were not modified.
