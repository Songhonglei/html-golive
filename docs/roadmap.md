# OpenGoLive development plan and prioritized backlog

Updated: 2026-11-03. [中文版](roadmap.zh-CN.md)

Prioritize reliable single-instance, intranet and AI Agent publishing: deliver the accepted fixes, make upgrades/recovery and automation failures verifiable, then expand collaboration and infrastructure. Work follows milestone gates rather than unconfirmed dates. `0.9.8` is a candidate for the next release, not a published version or a release-date commitment.

## Status and evidence

- Diagnostics, CLI, full acceptance and REL-01 lifecycle protection were merged via [PR #7](https://github.com/Songhonglei/html-golive/pull/7) as `c0c54cbf4c97f694a8c59e2044aacacce7cb5782`; runtime baseline: `3af077b`.
- All eight CI checks passed at the runtime baseline; 1182 local tests passed. Earlier independent f2d8254 diagnostic acceptance passed 46 CLI checks and 125 regressions; REL-01 added 16 CLI commands and 143 focused regressions. These checks do not replace 0.9.8 artifact/upgrade acceptance.
- A 16-stage MySQL/Chrome full-acceptance run has passed. The Docker sandbox branch and remote MySQL TLS remain unverified, rather than confirmed defects. Passing PostgreSQL/Supabase CI does not imply every manual acceptance scenario has run.
- This plan tracks execution: REL-01/REL-02 are complete; REL-03 candidate 0.9.8 source/Skill preparation is in progress. Official publication and business deployment are outside this execution. See the [candidate checklist](release-0.9.8.md).

## Implemented; awaiting release delivery

Do not schedule these as new feature work. Carry them into version, installation and upgrade acceptance.

| Capability | Current state | Remaining delivery |
| --- | --- | --- |
| context/doctor port precedence, record PID/HOME identity, drift reporting | Implemented and independently accepted | Candidate version alignment and release-artifact regression |
| Admin test defaults to the running backend; labelled button/result and safe target | Implemented; real MySQL/Chrome accepted | Repeat against installed release artifact |
| MySQL location; separate application-table/model counts | Implemented | Artifact acceptance; scale work remains DATA-02 |
| CLI sort, page controls, JSON mutations, db init help | Implemented | Script compatibility and error-code regression |
| SSL/proxy/MySQL diagnostics; isolated MySQL helper | Implemented; native sandbox lifecycle accepted | Environment coverage under ENV-01/ENV-02 |
| verify --full, browser/SQL/restart evidence and private reports | Implemented; local SQLite/MySQL passed | Artifact acceptance; broader matrix under QA-01 |

## Complete backlog

P0 gates the next release. P1 addresses data and automation reliability. P2 follows demonstrated collaboration demand. P3 starts only when its stated trigger is met. “Pending” is neither an implementation promise nor a declaration of a discovered fault.

| ID | Priority | Work and user benefit | Status / dependencies | Acceptance criteria |
| --- | --- | --- | --- | --- |
| REL-01 | P0 | Protect service identity boundaries in stop/restart/start; avoid affecting unrelated processes or reusing wrong settings | Complete; all eight CI checks passed and code merged, [#8](https://github.com/Songhonglei/html-golive/issues/8) | Reproduce reused PIDs, PID/HOME mismatch and missing health with isolated processes; establish reliable identity before signals; define and test behavior when identity cannot be confirmed |
| REL-02 | P0 | Review and merge PR #7 so users receive accepted fixes | Complete; PR #7 merged | Required CI and independent acceptance pass on final code; no known release blocker; retain review/evidence |
| REL-03 | P0 | Align release versions, docs and artifacts; avoid different code under the same version | In preparation; source version aligned, artifact build/acceptance pending, [#9](https://github.com/Songhonglei/html-golive/issues/9) | Package/CLI/health/Skill/changelog versions agree; build wheel, sdist and Skill distribution; artifact origin and checksums traceable |
| REL-04 | P0 | Accept clean install, upgrade and basic rollback from candidate and official sources | Pending; after REL-03 | Install outside checkout in a fresh environment; independent CLI and MySQL/Chrome full acceptance; upgrade from old release, confirm running code/data and rollback boundaries; repeat after separately authorized publication |
| DATA-01 | P1 | Exercise backup, restore and migration to protect pages and business data | Pending; build on existing export/import/migrate | Restore into fresh HOME/dedicated DB; compare pages, row counts/content hashes and critical settings; exercise damaged archives, conflicts, failure/interruption; document exclusions, credentials and external resources |
| OPS-01 | P1 | Upgrade/restart/failure-recovery runbook; reduce user and Agent troubleshooting | Pending; alongside REL-04/DATA-01 | Isolated rehearsal of backup, version-drift detection, failed-restart diagnosis, recovery and cleanup; commands match actual version and preserve business resources |
| AUTO-01 | P1 | Stabilize Agent/CLI contracts and failure paths | Pending; preserve list/get and legacy flags | Verify exit codes, JSON fields/error codes, repeated runs, timeouts and lost connections; no credential leaks; scripts can decide outcomes without parsing human prose |
| DATA-02 | P1 | Accurate, scalable aggregation/search/sorting/pagination | Pending; establish baseline first | Datasets exceed existing 10,000-row aggregation and 2,000-row search bounds; push aggregation/filtering into DB where possible; never present truncated results as complete; stable pagination and measured query/resource baselines |
| ENV-01 | P1 | Accept Docker MySQL sandbox and failure cleanup; reduce setup friction | Unverified; isolated Docker environment required | start/stop/cleanup, retries, port conflicts, missing daemon/image failures covered; private credentials, no secret output; preserve existing containers/volumes; claims match coverage |
| ENV-02 | P1 | Accept remote MySQL TLS and proxy paths; explain connection failures | Unverified; authorized controlled TLS environment required | Valid cert passes; wrong hostname/untrusted CA fail; proxy inheritance/timeouts explained; never disable certificate verification; distinguish from local-DB success |
| QA-01 | P1 | Complete coverage matrix and boundaries for four backends | Pending; extend existing CI/reports | Separate contracts, real browser, SQL/server evidence, restart and migration; label each backend/scenario passed/failed/skipped/unverified; supported failures cannot silently downgrade to overall success |
| COLLAB-01 | P2 | Detect editing conflicts; prevent users/Agents overwriting one another | Pending; schedule after concurrent-edit demand | Version/hash supplied with save; stale writes return explicit conflict and preserve saved content; reload/compare path; two editors and Agent retries covered |
| AUTH-01 | P2 | Group-based site permissions; reduce per-user administration | Needs confirmed demand; preserve individual roles | Define personal/group precedence, inheritance and revocation; deny unauthorized requests; prompt revocation and complete audit; identity-source and migration design |
| SCALE-01 | P3 | Shared sessions and inventory of local state dependencies | Demand-triggered; after reliability work | Confirm dual-instance/load-balancing need; inventory sessions, keys, files, configuration, caches and jobs; login/logout/revocation consistent across two instances; single-instance users require no added infrastructure |
| STORE-01 | P3 | WebDAV adapter; reuse NAS/Nextcloud/company storage | Demand-triggered; real target storage/user required | Confirm NAS/WebDAV use case and endpoint; publish/read/delete, timeouts, auth and cleanup pass storage contracts; shared page files with server-only credentials; document separate DB/session/backup responsibilities |

REL-01 was reproduced and fixed: stop at ce7b3aa terminated this run's unrelated Python sleeper in a fresh HOME. PID/HOME checks now guard stop, escalation and startup; restart aborts after failed stop and invalid/replaced records are preserved. Independent CLI acceptance and all 16 real MySQL/Chrome stages passed. See [REL-01 validation](validation-rel01.md). Only newly created test resources were controlled; existing acceptance services/databases were not modified.

## Milestone order

| Milestone | Scope | Entry condition | Deliverable / exit gate |
| --- | --- | --- | --- |
| M0: deliver fixes | REL-01 → REL-02 → REL-03 → REL-04 | Traceable implementation and acceptance | Review, final CI and install/upgrade acceptance complete; official-source checks follow authorized release. Candidate 0.9.8; exclude new collaboration/storage features |
| M1: single-instance reliability | DATA-01 + OPS-01 → AUTO-01; ENV-01/ENV-02/QA-01 as environments become available | M0 delivered; isolated resources/evidence directories ready | Repeatable recovery drills, Agent failure paths and environment matrix; missing environment remains unverified |
| M2: growing datasets | DATA-02; continue QA-01 | Dataset/performance baseline and measurable targets | Correct large-data aggregation/search/pagination; measured improvements; preserve CLI/page contracts |
| M3: team collaboration | COLLAB-01, then AUTH-01 when justified | Demonstrated multi-editor or team-permission need | No silent overwrite; explicit permission rules, audit and regression evidence; release number decided separately |
| Demand-triggered | SCALE-01 / STORE-01 | Dual-instance or actual NAS/WebDAV trigger, respectively | Define design and acceptance boundaries, then schedule separately; roadmap inclusion alone does not start implementation |

Do not invent dates or effort estimates before capacity and environments are confirmed. Split work into issues/PRs before implementation, recording dependencies, acceptance cases, evidence paths and actual coverage. Update task status after delivery; reprioritization must explain user benefit and displaced work.

## Boundaries

- Single-instance Agent publishing, clear diagnosis, recovery and accurate data come first. Shared sessions have little benefit for local CLI/static-token users and must not introduce mandatory shared infrastructure.
- WebDAV adapts page-file storage; it does not automatically provide hosting, shared login, group permissions, database backup or availability guarantees.
- TLS/Docker gaps do not automatically mean the product is unusable; document actual supported/verified scope until evidence exists.
- Existing security scanning, permissions and redaction remain release regression requirements. Updating this plan does not authorize merges, publication or deployment.

References: [Full acceptance](acceptance.md) · [Historical validation](validation-2026-10-21.md) · [Backup/restore/migration manual](manual.md) · [Upgrading](upgrading.md)
