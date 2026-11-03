# 0.9.8 candidate delivery checklist / 候选版本交付清单

Updated: 2026-11-03. Tracking [REL-03/REL-04 issue #9](https://github.com/Songhonglei/html-golive/issues/9).

**Candidate source only; not published.** Do not install `html-golive==0.9.8`
from a public index until an actual release exists. Published examples remain
pinned to `0.9.7.post1`; package/CLI/health/bundled Skill in this candidate use
`0.9.8`. No tag, GitHub release, PyPI upload or SkillHub/ClawHub upload is part
of preparation.

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
- [ ] Candidate wheel and sdist built by the standard backend with a successful exit.
- [ ] Complete artifact manifest includes wheel/sdist/Skill metadata and SHA-256.
- [ ] Fresh environment outside the checkout installs the exact wheel; CLI,
      imported module, distribution metadata and bundled Skill all agree.
- [ ] Candidate MySQL/Chrome full acceptance and service-control regressions pass.
- [ ] Upgrade from `0.9.7.post1` in a disposable HOME/database preserves content,
      identifies stale running code and restarts the intended process.
- [ ] Backup/rollback rehearsal defines restored data/configuration and exclusions.

The local standard build of the preceding runtime snapshot produced a source
archive but was interrupted during temporary-file cleanup by automatic approval
review (50 deletions in the turn). Its completed sdist was recovered and checked;
that does **not** make the candidate 0.9.8 build pass. Generated directories were
retained. Do not bypass the cleanup guard or substitute a manually assembled
wheel for standard-backend acceptance. Allow cleanup of the specific generated
build resources before retrying local distribution builds.

## Reproducible artifact acceptance

After approved build cleanup, build the candidate with the normal backend and
record command exit status:

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

本分支只准备 0.9.8 候选源码、版本和分发清单，不发布。REL-01/REL-02 已完成，
运行时代码基线的测试与 CI 全部通过；它们不能代替 0.9.8 的安装、升级和回退验收。

本地标准打包曾被自动审批拦截临时目录清理（本轮累计 50 项删除），生成文件已保留。
需允许清理明确的本轮构建资源后，再用标准构建后端完成 wheel/sdist 和独立安装验收。
不能把恢复出的旧源码归档或手工组装的 wheel 当作 0.9.8 标准构建成功。

所有产物需记录版本、清单、SHA-256、真实导入路径及独立验收证据。正式发布范围需另行确认，
发布后分别从正式源安装验证；不得把本地候选、GitHub、PyPI 和两个 Skill 平台的结果混为一谈。
