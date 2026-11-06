# 0.9.8 candidate delivery checklist / 候选版本交付清单

Updated: 2026-11-06. Tracking [REL-03/REL-04 issue #9](https://github.com/Songhonglei/html-golive/issues/9).

**Candidate artifacts only; not published.** Do not install `html-golive==0.9.8`
from a public index until an actual release exists. Published examples remain
pinned to `0.9.7.post1`; package/CLI/health/bundled Skill in this candidate use
`0.9.8`. No tag, GitHub release, PyPI upload or SkillHub/ClawHub upload is part
of preparation.

## Development follow-up

The [P0–P3 stage summary](stage-summary-0.9.8.md) records the candidate integration
and the fixed-commit [P3 independent reacceptance](validation-p3.md#independent-reacceptance).
The historical artifact gates below refer to their own artifact baseline.

DATA-01 source now implements identity-preserving business restore and migration;
see [its validation](validation-data01.md) and the [recovery runbook](recovery.md).
This does not change the historical accepted `f0de446` artifacts or results below.
A separately built and installed P1 artifact is bound to runtime fix commit `409a713`;
its independent MySQL/Chrome and exact recovery/rollback results are recorded in
the DATA-01 validation. Publication still requires an explicit final artifact selection.

## Completed inputs

- [PR #7](https://github.com/Songhonglei/html-golive/pull/7) merged as
  `c0c54cbf4c97f694a8c59e2044aacacce7cb5782` (runtime baseline `3af077b`).
- Eight CI checks passed, including Python 3.9/3.11/3.12, macOS, PostgreSQL,
  MySQL, Supabase and installed-wheel smoke tests in the build job.
- Local runtime regression: 1182 passed, 87 skipped, 643 subtests passed.
  Focused lifecycle regression: 143 passed; independent CLI: 16 commands;
  actual MySQL 8.4.13/Chrome: all 16 full-acceptance stages passed.

These inputs apply to the runtime baseline. Candidate version/artifact and
upgrade checks below must still be recorded separately.

Candidate source regression after version alignment: **1182 passed, 87 skipped,
643 subtests passed** (111.30s). The local log is
`.artifacts/rel01/candidate-source-suite.log`; this runs the checkout, not an
installed 0.9.8 wheel.

## Candidate gates

- [x] Runtime fixes reviewed, final baseline CI passed, PR #7 merged.
- [x] Candidate package, CLI, health and bundled Skill source versions aligned.
- [x] Published documentation remains explicit about candidate vs published code.
- [x] Candidate source regression passes; Skill ZIP contents and version checked.
- [x] Candidate wheel and sdist built by the standard backend with a successful exit in CI.
- [x] Complete artifact manifest includes wheel/sdist/Skill metadata and SHA-256.
- [x] Fresh environment outside the checkout installs the exact wheel; CLI,
      imported module, distribution metadata and bundled Skill all agree.
- [x] Candidate MySQL/Chrome full acceptance and service-control regressions pass.
- [x] Upgrade from `0.9.7.post1` in a disposable HOME/database preserves content,
      identifies stale running code and restarts the intended process.
- [x] Backup/rollback rehearsal defines restored data/configuration and exclusions.
- [ ] Exact record-identity restore: existing limitation tracked in [#11](https://github.com/Songhonglei/html-golive/issues/11), DATA-01. This is not passed by the content-restore check.

## Accepted artifact baseline

The [CI build job](https://github.com/Songhonglei/html-golive/actions/runs/41617774540/job/125855421170)
completed `python -m build`, archive checks and installed-wheel smoke tests.
All eight checks passed on source commit `f0de4468c603637043e2ec5fc136558b32f38f57`.
GitHub checked out its PR merge commit `7cecc3aa827b917657132e580eb3e648abdf8894`;
the artifact manifest records both commits. Later checklist-only documentation
changes do not change this accepted artifact identity.

Download the Actions artifact `distributions-f0de4468c603637043e2ec5fc136558b32f38f57`
(artifact ID `13222545401`); its ZIP SHA-256 is
`56eea0de1e429a368ee7638d4b9d4bdbaf8e974fe94a4a7b544e09767cc4c96a`.
These are CI acceptance artifacts, not a public package release.

| File | SHA-256 |
| --- | --- |
| `html_golive-0.9.8-py3-none-any.whl` | `5bf49c4c00ab33688d7b9f3d7ee30c1bb62f426f3066773f32a1399cc9b4f024` |
| `html_golive-0.9.8.tar.gz` | `d80741c2e5c675180cb2981f8418ff2745c74358cde1c38e0309b3685c14fbda` |
| `html-golive-skill-0.9.8.zip` | `b9ed73e1197a85ce5cce652a28a7d48d64f80c33b37ff5d76352ebb1c79fd182` |

Independent local acceptance downloaded these exact files, verified hashes and
matched all 120 wheel runtime files to the source. A fresh Python 3.12 environment
outside the checkout imported the installed package, with distribution, CLI,
health and bundled Skill version all `0.9.8`. Tests came from the sdist without
placing checkout runtime code on the import path.

- Installed lifecycle/context/doctor regressions: **142 passed** (29.69s).
- Independent installed CLI lifecycle: **16 commands passed**.
- Actual MySQL 8.4.13 + Chrome full verification: **all 16 stages passed**, including
  SQL evidence, admin backend selection, update/upsert/sort/pagination and restart.
- MySQL upgrade/code rollback: **9 checks passed, 1 known restore limitation**.
  Installing new code left the old service running; doctor retained its valid
  identity and reported version drift. Restart changed PID/version and preserved
  page bytes and data. Downgrading to the published `0.9.7.post1` wheel read both
  candidate-updated and candidate-created rows.

The pre-upgrade export restored page bytes and logical row content into a new
dedicated MySQL database, but **regenerated row IDs**. It is not an exact backup
restore; references to old IDs may break. This behavior also exists in the
published old wheel. Sort indices, timestamps and cross-row references are not
proven preserved here. DATA-01 / #11 must define and test that contract separately.
Configuration was copied separately; credentials, Agent state, audit history and
external resources are outside the export. No general downgrade compatibility
claim follows from this fixture.

Local evidence (private, not committed): `.artifacts/release-0.9.8/` contains the
CI manifest, installed provenance, lifecycle report, installed test log,
`mysql-full/` browser/SQL evidence and `upgrade/` report/CLI log/SQL evidence/backup.
Earlier failed harness attempts are retained separately: the first used a browser
field name for a CLI row; the second exposed the record-ID restore limitation.

The original three approved temporary directories were removed. A new local build
again exited 2 when automatic approval review rejected temporary cleanup at 50
deletions; its generated directories remain. This local failure was not bypassed
or counted as a build pass. The artifacts accepted above came from the separately
successful CI standard build, not the interrupted local build or a manual wheel.

## Reproducible artifact acceptance

Build with the normal backend in a permitted environment and record command exit
status, or download the retained CI artifacts and verify their provenance:

```sh
python -m build
```

Inspect both archives and Skill distribution; retain file lists and hashes.
Install the exact wheel into a new virtualenv and run from outside the source
checkout. Verify `importlib.metadata.version('html-golive')`, `golive.__file__`,
`golive --version`, `/health.version` and bundled Skill metadata. Use an isolated
HOME/config/database; do not silently inherit business credentials.

Run basic verification, focused lifecycle regressions and:

```sh
golive verify --full --browser-channel chrome --json --report-dir <new-private-report-directory>
```

Use a real supported browser and an authorized isolated database. Record every
passed/failed/skipped/unverified scenario, SQL evidence and browser logs.
Do not count existing 0.9.7.post1 runtime reports as candidate 0.9.8 results.

## Later publication gate

Publication is separate from preparation. Only after candidate gates pass:
confirm publication scope, create the intended tag/release, upload matching
artifacts to explicitly authorized registries, then reinstall from official
sources and repeat install/upgrade acceptance. Verify every registry separately;
a GitHub release or local upload exit is not proof that PyPI/SkillHub/ClawHub
serves the correct version. Docker sandbox and remote MySQL TLS remain distinct
coverage items until actually exercised.

## 中文说明

本分支准备 0.9.8 候选源码和产物，不发布。REL-01/REL-02 已完成；REL-03 已有
标准 CI wheel/sdist/Skill、提交号及哈希。候选安装验收使用下载的精确 CI wheel，
在源码目录外完成：142 项服务回归、16 次 CLI、MySQL/Chrome 全部 16 项均通过。

MySQL 升级/代码回退 9 项通过，另有 1 项已有恢复限制：导入新库会重新生成记录 ID，
已登记 #11 / DATA-01。页面字节和记录内容恢复不等于 ID、引用、排序和时间戳全部保真。
本次代码降级能读取候选版写入的数据，不代表任意 0.x 版本间都能安全降级。

原先授权的三个临时目录已清理。新的本地打包仍被自动审批拦截临时目录清理
（本轮累计 50 项删除），生成文件已保留；该失败未被绕过，也不计为本地构建通过。
本轮安装验收使用的是独立成功的标准 CI 构建产物。

所有产物需记录版本、清单、SHA-256、真实导入路径及独立验收证据。正式发布范围需另行确认，
发布后分别从正式源安装验证；不得把本地候选、GitHub、PyPI 和两个 Skill 平台的结果混为一谈。
