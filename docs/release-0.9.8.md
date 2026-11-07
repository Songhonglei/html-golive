# OpenGoLive 0.9.8 release

Release date: 2026-11-07. Package, CLI, health endpoint and bundled Agent Skill use **0.9.8**.

## Distribution

- [PyPI html-golive](https://pypi.org/project/html-golive/0.9.8/): Python wheel and source distribution.
- [GitHub v0.9.8](https://github.com/Songhonglei/html-golive/releases/tag/v0.9.8): wheel, sdist, Agent Skill ZIP, SHA-256 checksums and release verification receipt.
- The wheel bundles the matching Skill. Run `golive skill install --force` to update an existing copy; the installer preserves a backup.
- SkillHub and ClawHub are checked separately. Their processing or review state does not establish PyPI or GitHub availability; use the matching GitHub Skill ZIP when a registry has not made the new version available.

```sh
python -m pip install --upgrade 'html-golive==0.9.8'
golive --version
golive serve restart
golive skill install --force
golive doctor
golive skill status
```

Restart only an instance you intend to upgrade, with its existing environment and GOLIVE_HOME. Installing a package does not replace a running process. Back up business data and configuration before upgrading; see [upgrading](upgrading.md) and [recovery](recovery.md).

## Included changes

- Validate PID, HOME and health identity before service control; reject ambiguous stop/restart/start operations and report configuration or version drift.
- Preserve business record IDs, JSON values, sort indices and timestamps during supported restore and migration operations, with conflict detection and readback checks.
- Improve large-data statistics, filtering and pagination, CLI JSON/error contracts, environment diagnostics and isolated MySQL verification.
- Detect stale local editor writes, retain drafts for comparison, and add team groups with permission revocation and transactional audit.
- Persist OIDC login and one-use callback state; optionally share control state between same-host instances.
- Add WebDAV page storage with authenticated TLS, scoped paths, snapshots and rollback.
- Localize editor/conflict UI and validate the installed wheel without importing checkout runtime code.

See [CHANGELOG](../CHANGELOG.md), [P0–P3 implementation and acceptance](stage-summary-0.9.8.md), [collaboration](collaboration.md), [shared state](shared-state.md) and [WebDAV](webdav.md).

## Validation and artifact identity

The integrated runtime baseline is main commit `a728959a5a358a81cc91a7b346f3f5b221877895`. Its [post-merge CI](https://github.com/Songhonglei/html-golive/actions/runs/42172618011) completed successfully. Release-facing documentation and Skill instructions are synchronized separately; the release attachment `artifact-manifest.json` identifies the exact final build commit and SHA-256 of each package.

The release verification receipt records final archive checks, installed version/module provenance, fresh installation, service health, page publishing and upgrade checks. Each distribution channel is verified independently after upload. Historical runtime and browser results remain limited to their recorded commits and environments:

- [P1 data and environment validation](validation-p1-remaining.md), [identity-preserving recovery](validation-data01.md).
- [P2 validation](validation-p2.md), [localization and installed-package follow-up](validation-p2-ui01.md).
- [P3 independent acceptance](validation-p3.md#independent-reacceptance) of the CI wheel for `92fc7fa366263e815163e39ded441180bafc3937`, including same-host browser login/restart/revocation/logout and public wölkli WebDAV lifecycle checks.

The [archived candidate checklist](release-0.9.8-candidate-history.md) describes earlier f0de446 artifacts. Those files predate the DATA-01 identity-preserving recovery fix and are not the final release artifacts. Retain their historical findings; do not reuse their hashes or results as final release acceptance.

## Supported boundaries

- Atomic conditional editor writes require local storage on macOS/Linux. S3, Supabase and WebDAV protected editor saves return 501 until conditional writes are implemented; ordinary supported publishing and reads remain available.
- Shared login/control state was accepted on same-host local APFS. Cross-host high availability and production gateway/IdP configurations require target-specific validation.
- Public WebDAV acceptance covered the recorded wölkli account. Other NAS, Nextcloud and WebDAV providers require their own compatibility checks.
- SQLite, PostgreSQL, MySQL and Supabase coverage is recorded per backend. Controlled local TLS/proxy results do not establish every external enterprise network configuration or production SLA.
- Business export is not a backup of credentials, Agent state, external resources or all control-state audit history. Back up the relevant state stores separately.

## 中文说明

0.9.8 汇总已实现的 P0 至 P3 首批能力，统一包、CLI、服务 health 与 Skill 版本。安装升级使用正式分发的 0.9.8；运行服务需重启，已安装 Skill 需同步更新。

最终版本的提交、wheel/sdist/Skill 哈希与安装升级结果以 GitHub Release 附件为准。历史候选的记录 ID 恢复问题已由 DATA-01 修复；旧候选产物的哈希和验收不能替代最终制品验证。同主机共享状态、指定 WebDAV 服务及本地编辑冲突检测的适用范围保持上述限制。
