# 四数据库后端验收记录

日期：2026-10-19。基线：GitHub main `1fb24cb`（v0.9.6）。本次变更仍为 Unreleased，未覆盖已发布的 PyPI 包。

## 范围与结果

| 后端 | 实例 | 已验证链路 |
|---|---|---|
| SQLite | 独立临时目录 | registry、JSON CRUD、HTTP、CLI verify、导入导出、浏览器 TemplateAPI |
| PostgreSQL | 本机独立 PostgreSQL 17 数据库 | 同上，加原 PostgreSQL 专项回归、连接探针回滚 |
| MySQL | 本机独立 MySQL 8.4 数据库 | 同上，加字符集/大小写、DSN、TLS 配置、连接探针回滚 |
| Supabase | 官方 CLI 2.121.0 原生隔离实例 | 真实 Postgres / PostgREST / Auth / Storage；公开密钥 CRUD、RLS 越权拒绝、registry、中文存储与回滚、导入导出、CLI verify、浏览器 |
| Supabase 云端复验 | custom-course-platform-staging | 旧版 anon JWT、新版 publishable key 的 CRUD、RLS、CLI verify；云端 registry + 本地 HTML storage 的导入导出；真实浏览器 CRUD、upsert、排序、分页、保存后显示 |

云端仅创建随机命名的专用测试表，未读取或修改原业务表；验收后删除测试表。项目按授权恢复并保持可用。云端 Storage 未单独验收，完整 Storage 链路在本机真实 Supabase 服务上验收。

SQLite、PostgreSQL、MySQL 六个有向业务数据迁移组合，以及 Supabase 与这三者的六个有向组合，全部用真实数据库验证内容往返。切换后端不会自动迁移。迁移保留源数据，业务记录 ID 可能改变。

## 本次修复

- 新增 MySQL registry/data 驱动、依赖、配置、CLI、后台连接检查和 HTTP 数据访问。
- PostgreSQL / MySQL 共用参数绑定的 SQL CRUD 实现，原 PostgreSQL 专项回归继续执行。
- Supabase verify 从“跳过数据测试”改为使用页面公开密钥真实增删改查；清理失败计入最终失败状态。
- 兼容新版不透明 API key 与旧版 JWT；服务器请求拒绝携带凭证跟随重定向。
- 备份恢复扫描识别公开 Supabase key，仍检查脚本其余内容；禁止把 service/secret key 注入页面。
- 修复 SQLite / SQL 数据名称前缀中的 `%`、`_` 被当作通配符的问题。
- SQL 建表语句可在没有数据库连接和驱动时输出。

## 回归与构建

完整回归：**1176 passed、643 subtests passed、1 skipped**（164.89 秒）。跳过项专门验证未配置 PostgreSQL DSN 的场景；真库回归环境配置了 DSN，因此该项另行在无 DSN 环境执行。

收尾边界验证：Supabase 公开密钥、Storage 重定向和后台 UI 等 63 项通过；另在无 PostgreSQL DSN 的环境运行完整 verify 专项，15 项通过，包含前述跳过场景。

CI 新增 MySQL 8.4 和真实 Supabase 服务验收；明确检查实际执行的用例数，避免全跳过被误报为成功。Supabase CI 同时执行真实 Storage/RLS 和跨后端迁移。

构建 wheel / sdist 成功，`twine check` 通过。wheel 包含 MySQL 驱动适配、共享 SQL stores、Supabase 公开密钥保护模块，并声明 mysql extra。未向 PyPI 上传开发构建。

## Skill 审查完整结果

使用 `skill-release-audit`，结果：0 ERROR、4 WARN。

| 模块 | 状态 | 原始问题 |
|---|---|---|
| 模块1 语法与逻辑 | WARN | 引用了不存在的文件: golive.yaml（两条） |
| 模块2 功能完整性 | PASS | 无 |
| 模块3 边界与异常处理 | PASS | 无 |
| 模块4 数据与配置安全 | PASS | 无 |
| 模块5 依赖检查 | PASS | 无 |
| 模块6 文档规范 | WARN | frontmatter name='html-golive' 与目录名 'skill' 不一致 |
| 模块6 文档规范 | WARN | frontmatter 包含非标准字段: displayName, slug |

处理判断：`golive.yaml` 是使用者的运行时配置，不是 Skill 附带文件；`resources/skill` 是 Python 包内目录，安装后的目录名为 html-golive；displayName / slug 是现有 Hub 元数据。保留这些兼容约定，无须按通用审查规则改动。

使用与复验方法见[四种数据库后端的配置与验收](backend-validation.md)。
