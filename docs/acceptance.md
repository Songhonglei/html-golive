# Database diagnostics and full acceptance

Changes after `0.9.7.post1`; source checkout required until the next release.

`golive context --json` resolves the probe port from explicit `--port`, a live
managed service record in the current `GOLIVE_HOME`, `server.port`, then 8787.
`server.port_source` identifies the choice (`cli`, `service_record`, `config`,
`default`). Stale or invalid records are ignored. The command stays read-only.
`doctor` follows the same precedence, including explicit `--port 8787`.

The admin Data backend screen uses the **running configuration**, even if a
saved backend setting still needs a restart. The test selector starts at that
backend. The button identifies its selected target, and both successful and
failed diagnostics identify the actual backend and a credential-free target.
MySQL shows host, port, database and application table; DSN users, passwords and
TLS key paths are omitted. Application table count means the configured
TemplateAPI table (one), not every table in the database. Model and row counts
are separate, exact SQL aggregates for SQLite/Postgres/MySQL. Supabase model
statistics retain their existing 10,000-row scan bound.

## CLI data parity

```sh
golive data create --model-code acceptance --name example --content '{"text":"中文 🧪"}' --json
golive data update --id <record-id> --content '{"updated":true}' --json
golive data upsert --model-code acceptance --name example --content '{"v":2}' --json
golive data sort --id <record-id> --sort-index 100 --json
golive data list --model-code acceptance --page-no 2 --page-size 10
golive data delete --id <record-id> --json
```

List order matches TemplateAPI: descending `sort_index`, then descending
`created_at`. `--limit` remains supported; `--page-size` takes precedence.
Pages and sizes must be positive. Mutation JSON contains `ok`, `operation`,
`code`, `id`, `record`, and `error` on failure. Missing records and failed
deletes exit nonzero. Error codes include `invalid_arguments`, `invalid_input`,
`not_found`, `backend_disabled`, `backend_error`; backend exceptions are not
printed because they may contain credentials. List/get retain their existing
JSON shape. `--json` also makes operational errors machine-readable.

`db init` creates configured SQLite/Postgres/MySQL tables. For Supabase it
prints SQL for the SQL editor, since PostgREST cannot execute DDL.
`db init --print-sql` previews SQL without connecting or executing it.

## Optional full acceptance

The default `verify` remains a quick probe. JSON now explicitly declares
`mode: basic` and coverage that did not run. `ok: true` refers to that scope.

```sh
python -m pip install -e '.[mysql,verify]'
python -m playwright install chromium
golive verify --full --json --report-dir ./acceptance-report
# Alternatively, use an already installed Chrome, with an isolated browser profile:
golive verify --full --browser-channel chrome --json --report-dir ./acceptance-chrome
```

Full mode currently supports file-backed SQLite, MySQL and Postgres. It runs:

- CLI create/get/list/update/upsert (both branches)/sort/page two/delete.
- CLI publish and real HTTP health, using a random model and slug.
- Real browser TemplateAPI create/read/update/upsert/sort/pagination/delete,
  including Unicode, emoji, nested JSON and refresh.
- Direct SQL version/database/row evidence, compared with browser IDs/content.
- Admin default backend selection, target-labelled button and result, separate
  table/model counts, language switch and connection-probe rollback.
- Stop and replace only the temporary server process, then reload the page and
  confirm content, sort priority and row count persisted.

It never restarts an existing managed service. The browser must actually run;
a missing driver/browser or unsupported backend fails full mode. Later checks
are marked `skipped`, never passed. It does not claim remote TLS verification.
`--keep` retains the published test site; the temporary server always stops.
Cleanup targets only this run's random model/site, and cleanup failure fails
the overall result.

Reports include `report.json`, `report.md`, `sql-evidence.json`,
`admin-probe.json`, browser/CLI/server logs and screenshots. The directory is
private (0700), text files and screenshots are 0600, and known environment
credentials are redacted. Existing report directories are refused to preserve
evidence. An early failure may have no SQL evidence or screenshot; its report
lists precisely which steps ran.

## Isolated MySQL prerequisite setup

In a source checkout, use the stdlib-only helper. It never installs software
or starts a system-wide database service. Choose unused DB and golive ports.

```sh
python scripts/mysql_sandbox.py start --directory /tmp/golive-mysql-demo \
  --engine native --port 13306 --server-port 8788
# Or --engine docker (default image mysql:8.4.13; override with --image).
source /tmp/golive-mysql-demo/environment.sh
golive db init
golive context --json
golive verify --full --json --report-dir ./mysql-report
# Stop any golive service you started against the sandbox first:
golive serve stop
python scripts/mysql_sandbox.py stop --directory /tmp/golive-mysql-demo
# Explicit cleanup deletes this sandbox's database, credentials and GOLIVE_HOME:
python scripts/mysql_sandbox.py cleanup --directory /tmp/golive-mysql-demo
```

The helper refuses existing directories and occupied ports, requires native
MySQL 8.4+ or working Docker, binds TCP to loopback, disables MySQL X protocol,
creates a dedicated database/user, and stores random credentials in protected
files. `stop` preserves data. `cleanup` authenticates to this sandbox and removes
only its owned directory/container. A failed start preserves its private logs
for diagnosis. No local DB tooling is needed when a dedicated remote DSN is
already available. Docker execution still requires access to its daemon and
image registry; this is distinct from a successful native smoke test.

`doctor --json` adds `environment`: Python executable/SSL implementation,
urllib3 v2 compatibility, shell proxy variable **names** and detected system
proxy schemes, plus MySQL driver/DSN/local-tool availability. It makes no remote
TLS request. LibreSSL users should recreate the virtualenv with an OpenSSL
Python. When only a system proxy is detected, CLI/Homebrew downloads may need
proxy environment variables exported explicitly; values are never displayed.

## 中文说明

本轮修复优先解决“服务端口探测错误”和“后台误测其他数据库”。`context`、
`doctor` 的端口优先级为：显式参数 → 存活服务记录 → 配置 → 8787，JSON 中展示
`port_source`。后台以运行中的后端为准，默认选中当前后端，按钮明确显示“测试
MySQL”，结果显示实际后端、主机、端口、库名和应用表名，隐藏账号密码与 TLS 私钥路径。
应用表数量与数据模型数量分别展示，SQL 后端的模型/行数为精确聚合。

CLI 新增 `data sort --sort-index`、`--page-no`、`--page-size`，写入命令支持
`--json`，统一返回记录与稳定错误码。旧的 `--limit` 继续兼容。

使用 `verify --full` 执行完整验收；需安装 `[verify]` 和 Chromium，或使用
`--browser-channel chrome` 调用已安装的 Chrome。完整模式包含 CLI、真实浏览器、
更新、upsert 两条分支、排序、分页、刷新、SQL 证据、后台探针回滚与服务进程重启持久化。
报告逐项标注 passed/failed/skipped，缺少浏览器或 SQL 后端不可用时不会降级报成功。
默认基础模式会明确列出未执行的覆盖范围。当前完整模式支持 SQLite/MySQL/Postgres，
Supabase 继续使用基础验收；两种模式均不代表远程 TLS 已验收。

独立 MySQL 初始化使用上述 `scripts/mysql_sandbox.py`。脚本仅操作新建的专用目录、
库和账号，不安装全局软件、不改变现有 MySQL 服务，凭证文件权限为 0600。
`stop` 保留数据，显式 `cleanup` 才删除该沙箱。运行前会检查工具版本和端口；
`doctor` 补充 SSL、代理及 MySQL 前置条件诊断，并且不回显凭证或代理地址。
