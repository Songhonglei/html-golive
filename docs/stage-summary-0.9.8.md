# OpenGoLive 0.9.8 候选阶段总结

2026-11-06。整合范围从 0.9.8 候选交付准备到 P3 首批。0.9.8 仍为候选版本，正式制品发布和发布源验收属于后续交付门禁。

| 阶段 | 已完成的工作 | 证据 |
| --- | --- | --- |
| P0 候选交付 | 固化服务身份校验，保留可追溯的 wheel、sdist 和 Skill 产物。早期候选已完成 MySQL/Chrome 安装、升级和代码回退演练。 | [候选交付清单](release-0.9.8.md)，[PR #10](https://github.com/Songhonglei/html-golive/pull/10) |
| P1 数据与自动化 | 恢复和迁移保留记录身份及元数据。补齐大表查询、CLI 错误契约和 Docker MySQL 隔离验证。F01 截断 gzip 在访问恢复目标前拒绝。 | [恢复身份](validation-data01.md)，[P1 验证](validation-p1-remaining.md)，[F01 修复](validation-f01.md)，[PR #12](https://github.com/Songhonglei/html-golive/pull/12)，[PR #14](https://github.com/Songhonglei/html-golive/pull/14) |
| P2 协作 | 本地编辑用版本检查拒绝过期写入，保留草稿供比较。站点组权限支持撤权和审计。修复独立验收发现的编辑器本地化与安装包测试路径问题。 | [协作验证](validation-p2.md)，[独立验收后续修复](validation-p2-ui01.md)，[PR #17](https://github.com/Songhonglei/html-golive/pull/17) |
| P3 共享状态与存储 | 同主机双进程共享登录及权限状态。独立验收覆盖跨进程回调、重启、撤权和原 Cookie 登出失效。指定 wölkli 账号完成公网 WebDAV 认证、HTML 发布与读取、快照保留、指定回滚和清理。 | [P3 独立复验摘要](validation-p3.md#independent-reacceptance)，[PR #20](https://github.com/Songhonglei/html-golive/pull/20) |

P3 独立复验使用提交 `92fc7fa366263e815163e39ded441180bafc3937` 的 CI wheel。测试目录删除返回 204，使用同一正确凭证复查返回 404，账号根目录仍返回 207。此前 P1 和 P2 的验收发现保留在原报告，修复证据按各自提交记录。

共享状态的验收范围为同主机本地磁盘。外部生产 IdP、生产网关、跨主机共享和其他 NAS 或 WebDAV 服务仍需按目标验收。正式发布前需要选定最终制品，并按发布门禁完成安装与升级复验。
