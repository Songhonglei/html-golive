# Validation: diagnostics, CLI and MySQL acceptance improvements

Date: 2026-10-21 (Asia/Shanghai). Source base: `d38e2d0`, package version
`0.9.7.post1` with unreleased changes described in [acceptance.md](acceptance.md).

| Check | Actual result |
| --- | --- |
| Full regression suite, Python 3.12.13 | 1116 passed, 87 skipped, 643 subtests passed |
| Focused regression after final UI/report edits | 97 passed |
| Real SQLite/MySQL SQL and HTTP contracts | 31 passed, 9 skipped (Postgres DSN absent) |
| Real MySQL full acceptance | All 16 stages passed against MySQL 8.4.13 and installed Chrome |
| Wheel install in a separate virtualenv outside the checkout | All 16 SQLite full-acceptance stages passed using the installed wheel |
| Build | wheel and sdist built; runtime module present, tests excluded from wheel, sandbox script present in sdist |
| Compatibility | compileall and Python 3.9 AST syntax check passed; Python 3.9 runtime not exercised locally |
| Native MySQL sandbox lifecycle | start, protected credential files, dedicated account/database, stop and cleanup passed |
| Context/doctor on managed MySQL service | Correct port 18788, `port_source: service_record`, matching home/backend; doctor returned `ok: true` |
| Admin UI | MySQL selected by default, Test MySQL / 测试 MySQL, safe host/port/database/table, independent counts, successful probe rollback |

Full acceptance covers CLI CRUD/upsert/sort/page two, actual publication,
HTTP health, real browser CRUD/upsert/sorting/pagination/refresh, SQL evidence,
admin selection/probe rollback/language switch, and a replacement server
process reading persisted content/order/count. Temporary servers and this
run's random test models/sites were removed. The dedicated MySQL sandbox was
stopped and cleaned up after validation.

Local report directories in the development checkout:

- `.artifacts/mysql-reviewed/`: MySQL report, SQL evidence, browser/admin
  screenshots, probe result and browser/CLI/server logs.
- `.artifacts/wheel-sqlite-full/`: installed-wheel SQLite acceptance evidence.
- `.artifacts/pytest-final.log`, `.artifacts/pytest-mysql.log`: test summaries.

These are local, ignored artifacts, not files included in the repository.

The bundled Chromium download timed out; real browser checks used installed
Chrome through the explicit `--browser-channel chrome` option. Docker sandbox
execution, remote TLS, live Postgres and live Supabase were not tested in this
local run. Missing coverage is not represented as successful acceptance.
CI now includes full MySQL Chromium acceptance and artifact upload; its remote
result must be checked on the pull request. No package release or deployment
was performed.
