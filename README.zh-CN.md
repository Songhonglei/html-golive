# html-golive

> **自部署的一键 HTML 发布工具 —— 你的内网 Vercel-lite。**

一条命令把 HTML 文件、项目文件夹或压缩包变成可分享的 URL，跑在你自己的
电脑、NAS、VPS 或内网服务器上。零配置起步：本地存储 + SQLite 注册表 +
内置 HTTP 服务。

```bash
pip install html-golive

golive publish report.html --name "季度报告" --slug q3
# ✅ 发布成功 → http://localhost:8787/q3

golive serve            # 启动内置服务
```

## 功能

| 功能 | 状态 |
|---|---|
| 发布单 HTML / 目录 / 压缩包 | ✅ v0.1 |
| 资源打包（CSS/JS/图片内联为单文件） | ✅ v0.1 |
| base64 图片压缩（`--compress`，需 Pillow） | ✅ v0.1 |
| 19 种内置 CSS 美化风格（`--style`） | ✅ v0.1 |
| 短域名（保留字 + 占用双重校验） | ✅ v0.1 |
| 回滚（每站点保留 10 份快照） | ✅ v0.1 |
| 安全扫描（凭证/个人信息规则，YAML 可扩展） | ✅ v0.1 |
| 网页克隆（`golive clone <url>`，支持无头浏览器） | ✅ v0.1 |
| 实时预览 + 风格切换面板（`golive preview`） | ✅ v0.1 |
| 内置静态服务 + JSON API（`golive serve`） | ✅ v0.1 |
| 健康检查（`golive doctor`） | ✅ v0.1 |
| `golive.yaml` 配置加载（env 优先，`--config`） | ✅ v0.2 |
| 数据层：Supabase/PostgREST 驱动的 `window.TemplateAPI` / `window.SupabaseAPI` | ✅ v0.2 |
| Supabase 后端三件套：存储 bucket + 注册表 + 数据层 | ✅ v0.2 |
| S3 兼容存储与图床（MinIO/COS/OSS/TOS） | ✅ v0.2 |
| 内网页面迁移检查（`golive migrate-check`） | ✅ v0.2 |
| Docker Compose 部署（含可选 MinIO profile） | ✅ v0.2 |
| 浏览器在线编辑器 + 保存 API | 🚧 M3 |
| 水印 + 可选 LLM 安全复核 | 🚧 M3 |
| Token / OAuth 鉴权 | 🚧 M3（serve 模式的 token 基础能力 v0.1 已有） |

## 快速开始

```bash
# 1. 安装
pip install html-golive              # 需要图片压缩时：
                                     # pip install 'html-golive[image]'

# 2. 发布
golive publish index.html --name Demo --slug demo
golive publish ./my-project/ --slug app      # 目录 → 打包为单 HTML
golive publish site.zip                      # zip/tar.gz 同样支持

# 3. 启动服务
golive serve --port 8787
# → http://<你的主机>:8787/demo

# 管理
golive list
golive publish new.html --update demo        # 覆盖更新
golive rollback demo --dry-run               # 查看快照
golive rollback demo --yes                   # 回滚到最新快照
golive clone https://example.com --save-only # 克隆公网页面
golive preview draft.html                    # 热更新实时预览
golive styles                                # 查看 CSS 风格
golive doctor                                # 环境体检
```

## 数据目录

所有数据存放在 `GOLIVE_HOME`（默认 `~/.golive/`）：

```
~/.golive/
├── sites/<site_id>/index.html   已发布内容
├── backups/<site_id>/           回滚快照（最多 10 份）
├── registry.db                  SQLite 注册表
├── logs/                        审计日志
└── cache/                       风格备份等缓存
```

## 配置

零配置即可使用。可选项：

- `GOLIVE_HOME` — 数据目录（默认 `~/.golive/`）
- `GOLIVE_TOKEN` — 设置后 `/api/sites` 需要
  `Authorization: Bearer <token>`（或 `X-Golive-Token`）请求头
- `GOLIVE_FONT_CDN_BASE` — 将注入 CSS 风格中的
  `https://fonts.googleapis.com` 前缀替换为自定义字体镜像
  （如国内镜像 `https://fonts.loli.net` 或企业自建字体服务）
- `GOLIVE_UPLOADER_CMD` — 自定义图片上传命令模板
  （如 `mytool upload {file}`）；设置后打包图片走该命令上传，
  不再 base64 内联，详见 [docs/backends.md](docs/backends.md#imageuploader)
- `FIRECRAWL_API_KEY` — `golive clone` 的可选降级抓取通道（针对重 JS
  渲染页面）；默认不设置、不产生任何外部调用
- `golive.yaml` — 后端选型与规则扩展，见
  [golive.example.yaml](golive.example.yaml)。查找顺序：
  `--config <path>` → `$GOLIVE_CONFIG` → `./golive.yaml` →
  `$GOLIVE_HOME/golive.yaml`；环境变量永远覆盖 yaml 同项
- `GOLIVE_SUPABASE_URL` / `GOLIVE_SUPABASE_ANON_KEY` /
  `GOLIVE_SUPABASE_SERVICE_KEY` — Supabase 后端
  （详见 [docs/backends.md](docs/backends.md)）
- `GOLIVE_S3_AK` / `GOLIVE_S3_SK` — S3 后端
  （`pip install 'html-golive[s3]'`）

**网络行为说明**：golive 在发布/托管时不产生任何外呼。例外：`golive clone
<url>` 抓取目标页面；`golive preview` 首次运行会从 `cdn.tailwindcss.com`
下载一次性 Tailwind 缓存（离线时静默降级）；注入的 CSS 风格引用公网字体
CDN（可用 `GOLIVE_FONT_CDN_BASE` 替换）；以及你自己配置的
`GOLIVE_UPLOADER_CMD`。

## 安全扫描

每次发布都会按内置规则扫描（API key、私钥、数据库连接串、个人信息等）。
强特征命中直接阻断发布；弱特征命中仅告警。可用自己的 YAML 文件扩展规则，
确认误报时可用 `--skip-scan` 跳过。

## 数据层（v0.2）

静态页面接上你自己的 Supabase 项目即可获得完整读写能力，无需写服务端：

```bash
golive db init --print-sql              # 建表 SQL 粘到 Supabase SQL Editor
golive publish app.html --data-model myapp_v1
```

页面里直接调 `window.TemplateAPI`（命名空间化记录存储：list / listAll /
get / create / update / delete / sort / upsert）或 `window.SupabaseAPI`
（直连表操作：query / insert / update / delete）。签名是稳定契约——在
其他 golive 部署上开发的页面零改动可跑。完整指南（含 RLS 安全须知）：
[docs/data-layer.md](docs/data-layer.md)。从内网部署迁移页面：先跑
`golive migrate-check page.html`（[迁移指南](docs/migrate-from-intranet.md)）。

## Docker

```bash
docker compose up -d golive                 # golive serve 跑在 :8787
docker compose --profile minio up -d        # 加本地 S3（图床用）
```

## 路线图

- ~~**M1 — 内核**：发布/托管/回滚、风格、克隆、预览、安全扫描~~ ✅ v0.1
- ~~**M2 — 数据层**：Supabase 后端三件套、TemplateAPI/SupabaseAPI 注入、
  S3 适配器、migrate-check、Docker Compose~~ ✅ v0.2
- **M3 — 编辑与进阶**：浏览器在线编辑器（带版本化保存 API）、水印、可选
  OpenAI 兼容 LLM 安全复核、OAuth。

## 许可证

[MIT](LICENSE) © 2026 Songhonglei

---

English documentation: [README.md](README.md).
