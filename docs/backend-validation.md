# 四种数据库后端的配置与验收

SQLite、PostgreSQL、MySQL 和 Supabase 均支持站点目录（registry）和页面业务数据（data）。HTML 文件由独立的 storage 配置保存：前三者可搭配本地目录或 S3，Supabase 还可搭配 Supabase Storage。后台设置、审计、服务运行信息等本机控制数据仍保存在 `GOLIVE_HOME`。

> MySQL 是本轮 Unreleased 新增功能。正式发布前请在仓库中安装 `pip install -e '.[postgres,mysql]'`，使用该环境的 `golive`；已发布的 v0.9.6 包不包含 MySQL。

## 选择与配置

| 后端 | 安装 | 连接方式 | 页面访问业务数据 |
|---|---|---|---|
| SQLite | `pip install html-golive` | 默认本地文件，零配置 | golive `/api/data` |
| PostgreSQL | `pip install 'html-golive[postgres]'` | `GOLIVE_PG_DSN` | golive `/api/data` |
| MySQL 8.4+ | `pip install 'html-golive[mysql]'` | `GOLIVE_MYSQL_DSN` | golive `/api/data` |
| Supabase | `pip install html-golive` | 项目 URL + 公开密钥；服务器可另配私密密钥 | 页面直连 PostgREST，受 GRANT 和 RLS 限制 |

PostgreSQL / MySQL 示例，将两处 `mysql` 改成 `postgres` 即可切换：

```yaml
storage:
  backend: local
registry:
  backend: mysql
  mysql:
    dsn_env: GOLIVE_MYSQL_DSN
  postgres:
    dsn_env: GOLIVE_PG_DSN
data:
  backend: mysql
  templates_table: golive_templates
```

将 DSN 放入服务器环境，不要写入 HTML 或提交到 Git：

```bash
export GOLIVE_MYSQL_DSN='mysql://golive:YOUR_PASSWORD@127.0.0.1:3306/golive'
# 或
export GOLIVE_PG_DSN='postgresql://golive:YOUR_PASSWORD@127.0.0.1:5432/golive'
golive db init
golive doctor
golive verify --json
```

账号、密码中的保留字符需做 URL 编码。MySQL 远程连接默认校验证书和主机名，可用 `?ssl_ca=/absolute/path/ca.pem` 指定 CA。驱动使用 utf8mb4 和区分大小写的排序规则；model_code、name、user_id、version 最长 191 个字符。数据库和账号须预先建立，并授权建表及增删改查。

Supabase 的完整配置和建表/RLS 示例见 [数据层](data-layer.md) 与 [后端](backends.md)。公开密钥支持 `sb_publishable_...` 和旧版 anon JWT；`sb_secret_...` / service_role 仅供服务器使用，禁止注入页面。`golive db init --print-sql` 输出建表说明；还需显式配置表权限和 RLS。仅有私密密钥不足以通过页面数据验收。

## 验收闭环

每次切换后端后重启服务，并重新发布使用数据层的页面：

```bash
golive publish app.html --slug app --data-model notes
golive serve restart
golive doctor
golive verify --json
```

在浏览器中打开页面，使用相同的 `TemplateAPI` 完成创建、读取、修改、upsert、分页、排序和删除，再刷新页面确认持久化。管理后台可查看对应模型和记录。

- SQLite / PostgreSQL / MySQL 的后台连接测试会读写真实数据库并回滚探针。
- Supabase 的后台连接测试检查 Data API 可达性和可见表；`golive verify` 使用**公开密钥**执行真实 CRUD，能发现 RLS 隐藏记录或禁止写入的问题。
- `golive verify` 会清理测试页面和记录；清理失败也会返回失败，不应只看“连接成功”。它不能代替浏览器验证。
- 切换配置不会迁移数据。先 `golive export --output backup.tar.gz` 备份，再 `golive migrate data --to mysql --dry-run` 查看目标数据量；确认后执行迁移，修改配置、重启并重新发布。迁移保留源数据，业务记录 ID 可能改变，外部引用需单独处理。

## 自动化：真实数据库，不用 mock 冒充

在仓库根目录安装 `pip install -e '.[dev,postgres,mysql]'`。将 DSN 指向**专用测试数据库**：部分旧回归用例会清空固定测试表，禁止使用生产数据库。

```bash
python3 -m pytest tests/test_sql_backend_contract.py tests/test_backend_http_contract.py \
  tests/test_sql_backend_migration.py tests/test_postgres_backend.py tests/test_data_layer_e2e.py -q -rs
```

未配置的数据库用例会明确显示 skipped；跳过不代表通过。CI 分别启动 PostgreSQL、MySQL 8.4，并检查真实用例确实执行。

Supabase 真服务验收需额外配置以下环境变量（本机 Supabase 或专用测试项目均可）：

```text
GOLIVE_TEST_SUPABASE_URL
GOLIVE_TEST_SUPABASE_DB_DSN
GOLIVE_TEST_SUPABASE_ANON_KEY
GOLIVE_TEST_SUPABASE_SERVICE_KEY
```

```bash
python3 -m pytest tests/test_supabase_live.py -q -rs
```

该套件创建随机命名的独立表和私有 bucket，设置专用 RLS，测试公开密钥 CRUD、越权拒绝、registry、Storage 中文内容和回滚、发布、导入导出，以及与另外三种数据库往返迁移，最后删除测试资源。MySQL / PostgreSQL 往返还需各自的 DSN，并指向与 Supabase 源数据独立的测试数据库。只配置部分 Supabase 变量会直接失败，避免配置错误被当成跳过。CI 用固定版本的 Supabase CLI 启动隔离的真实 Postgres、PostgREST、Auth、Storage 服务，不需要云端凭证。
