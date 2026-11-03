# REL-01: service control identity acceptance

Date: 2026-11-03. Tracking: [issue #8](https://github.com/Songhonglei/html-golive/issues/8), [PR #7](https://github.com/Songhonglei/html-golive/pull/7).

## Reproduction and resulting behavior

At baseline `ce7b3aa`, an independent scratch HOME recorded the PID of this
run's live Python sleeper with an unused port. Calling `service.stop()`
returned `stopped`, terminated the unrelated sleeper and deleted the record.
No existing acceptance service/database was touched.

The fix uses the same `/health` PID and canonical HOME identity as diagnosis
before SIGTERM; it rechecks identity and the record before SIGKILL. Missing,
mismatched or unavailable identity returns `identity-unverified`, preserves
the process/record, and prevents restart from starting a replacement.
Confirmed dead records can still be cleaned. Restart inherits only a verified
host/port, falling back to configuration when no valid record exists.

Start rejects another HOME, an unverifiable live record and a second managed
endpoint; new-child health must identify the spawned PID and this HOME.
Replacement records are preserved. Existing version/backend drift remains
visible and does not itself prohibit lifecycle control. Legacy integer PID
records cannot authorize live-process control; invalid PID types are rejected.

## Actual verification

- The initial regression set demonstrated 25 failing cases against the old
  implementation; malformed-record tests guard the OS signal boundary.
- Final focused service, identity, context and init coverage: 143 passed.
- Independent real CLI subprocess acceptance: 16 command executions passed,
  including sleeper preservation, refusal to overwrite invalid records,
  idempotent start, refusal of a second endpoint, real restart with PID
  replacement, explicit port moves, reuse of a verified moved endpoint,
  normal stop and configuration fallback after a dead record.
- Real isolated native MySQL 8.4.13 plus Chrome full acceptance: all 16 stages
  passed, including SQL evidence, browser operations and restart persistence.
- Local full regression: 1182 passed, 87 skipped, 643 subtests passed.
  Final CI results are recorded on the PR for its exact head revision.
- Python 3.9 AST syntax and `git diff --check` passed. Runtime matrix coverage
  is assessed from CI rather than inferred from the local interpreter.

Local ignored evidence in the development checkout:

- `.artifacts/rel01/before.json` and `before-tests.log`.
- `.artifacts/rel01/acceptance/report.json` (CLI commands, exits and output).
- `.artifacts/rel01/focused-final.log` and `full-suite.log`.
- `.artifacts/rel01/mysql-full/` (16-stage report, SQL evidence, browser/admin
  screenshots and logs).

Only the test harness cleans its own processes/resources. Docker and remote
TLS were not tested in this run. These checks are not cryptographic endpoint
attestation or an atomic OS process-handle guarantee; an unresponsive service
whose identity cannot be reconfirmed is left for its original supervisor.

## 中文摘要

REL-01 已通过独立受控进程确认并修复：stop 发信号前核对 PID/HOME，强杀前重新核对，
无法确认身份时保留进程和记录；restart 停止失败即中止，不继承无效端口/主机。
start 不接管其他 HOME、不覆盖存活的无效记录、不误认新进程的 health。
全量回归 1182 项通过、87 项跳过；定向回归 143 项、真实 CLI 16 次、MySQL/Chrome 完整验收 16 项均通过。
现有验收环境未修改；正式发布未执行，Docker/远程 TLS 不在本次验证范围。
