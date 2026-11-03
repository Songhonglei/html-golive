# Recovery runbook / 恢复操作手册

This runbook accompanies DATA-01 development source. The previously accepted
0.9.8 CI artifact at `f0de446` still regenerates record IDs on import. Install
an exact source/wheel that includes the new restore contract and retain its
commit, package path and SHA-256; a version string alone does not identify it.
See [DATA-01 validation](validation-data01.md) and the [candidate checklist](release-0.9.8.md).

## 1. Identify and freeze the source

Run with the original project's explicit `GOLIVE_HOME`, config and protected
environment loaded. Keep outputs private; never paste DSNs or credentials:

```sh
golive --version
golive context --json
golive doctor --json
golive serve status
```

Confirm health PID/HOME and version/backend against the intended service. Code
installation does not replace a running process. If stop/restart refuses an
unverifiable record, inspect with context/doctor and use the original terminal or
supervisor to stop that known service. Do not delete the live record or signal
an unrecognized PID. After a failed restart, inspect before retrying.

Pause application writers during backup and recovery, including direct Supabase
clients and other database writers. Export does not provide one transaction
across registry, data and page storage. Counts cannot detect all concurrent edits.

## 2. Keep a complete recovery set

```sh
golive export --output <private-backup.tar.gz>
```

Retain the export's checksum, exact old/new packages, configuration and storage
settings separately. Store credentials through the existing secret mechanism;
export does not carry them. For local SQLite, stop writers before copying the
HOME; for external databases use their consistent backup facilities as well.
HTML/data exports exclude audit history, service records/logs, sessions/keys,
installed Agent skills, external infrastructure, and page rollback history.
Registry creation/update timestamps are not guaranteed to survive import.

Export checks counts and refuses a known short archive. This is useful evidence,
but it is not proof of a consistent live snapshot, full configuration recovery,
or every application's semantic validity.

## 3. Preview and restore into a fresh isolated target

Use a new HOME, page-storage location and dedicated database/schema/table. Set
the target config explicitly and load its dedicated credentials. Do not point
the rehearsal at production storage or a shared table. Preflight example:

```sh
golive import <private-backup.tar.gz> --dry-run --json
```

Preview validates archive structure/counts/data fields without opening target
backends. `target_inspected:false` and unknown conflicts do not certify target
connectivity or emptiness. Real restore:

```sh
golive import <private-backup.tar.gz> --yes --json
```

Require exit code zero and `ok:true`; inspect `data_identity_preserved`,
`data_exact_restore`, per-record `data_errors`, and any metadata defaults. For a
full-field archive restored into an empty supported target, business record IDs,
model/name/user, description, content, version, sort index and timestamps are
preserved. Timestamp formatting may normalize in PostgREST; instants must agree.
References encoded as IDs remain unchanged. Opaque content is never rewritten.

Verify independent SQL values and page hashes, owners/editability/maintainers,
application references and pagination/order. Restart the target and repeat reads.
Only switch traffic after these checks and application-specific checks pass.

## 4. Conflicts and partial failures

- `skip` leaves matching target records intact. Different content or a logical
  key with another ID makes exact restoration false; inspect the ID map.
- `overwrite` restores full business metadata only for the same ID/logical key.
  A different ID for the same key or a different logical record occupying the
  archived ID fails explicitly, preserving the conflicting target record.
- `rename` creates copies with new IDs and reports them. References in page/JSON
  content are not remapped; this is a clone operation, not an exact restore.

Import is not archive-wide atomic. `partial:true`, per-record failures and
uncertain-write flags require investigation. After a transient failure, repeat
with `skip` against the same target: already restored IDs remain stable and
missing records can be completed. A disconnect after commit can leave data even
when the response failed; read independently before deciding what to retry.
Never automatically delete a partially restored target containing unrelated data.
Use a fresh isolated target if conflict reconciliation is unclear.

Migration preserves business IDs/metadata; identical existing records are skipped,
and conflicting target records fail rather than being silently overwritten.
A repeated migration can legitimately report zero added and nonzero skipped.
Migration copies registry IDs for new sites; it does not move page files. Use
export/import for a complete page move and retain the original source.

## 5. Roll back code and routing

Stop only the verified candidate service, restore the exact old package, and
start with the original HOME/config/environment. Verify health version/PID/HOME,
backend and representative page/data reads. Keep the backup and previous routing
until application checks pass. Do not infer arbitrary schema downgrade safety
from one successful fixture; restore a consistent database/config/page backup
when code rollback alone is insufficient.

## 中文说明

先核对源服务身份并暂停全部写入者，再保存导出包、哈希、精确安装包及单独的配置/凭证恢复方案。
在新 HOME、独立存储和专用库中演练；预览只检查归档，不表示目标库可连或无冲突。

完整业务记录归档在空目标上保留 ID、内容、排序和时间戳；`skip` 保留已有内容，
`overwrite` 遇到不同 ID/逻辑身份时拒绝覆盖，`rename` 会生成新 ID 且不重写引用。
部分失败可能已经提交部分写入，应独立读取并按稳定 ID 重试。记录元数据缺省、失败、
不确定写入和实际 SQL/页面证据，不能只看一次 `ok:true`。

导出不包含配置、凭证、审计、会话/密钥、Agent 安装和外部资源；不保证站点时间戳和历史快照保真，
也不是跨数据库和文件的一致事务备份。新代码安装与服务重启分开核验，无法确认身份时交回原进程管理器。
