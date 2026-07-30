# html-golive

[![CI](https://github.com/Songhonglei/html-golive/actions/workflows/ci.yml/badge.svg)](https://github.com/Songhonglei/html-golive/actions)

> **自部署的一键 HTML 发布工具 —— 你的内网 Vercel-lite。**

一条命令把 HTML 文件、项目文件夹或压缩包变成可分享的 URL，跑在你自己的
电脑、NAS、VPS 或内网服务器上。

```bash
pip install html-golive

golive publish report.html --name "季度报告" --slug q3
# ✅ 发布成功 → http://localhost:8787/q3

golive serve
```

**零配置起步** —— 本地存储 + SQLite + 内置服务。
**随需生长** —— 一个 yaml 即可切换 Supabase 或任意 S3 兼容后端
（MinIO / 腾讯 COS / 阿里 OSS / 火山 TOS）。

---

## 目录

- [为什么选 html-golive](#为什么选-html-golive)
- [快速开始](#快速开始)
- [功能](#功能)
- [架构](#架构)
- [配置](#配置)
- [数据层](#数据层给静态页面一个数据库)
- [安全扫描](#安全扫描)
- [Docker](#docker)
- [路线图](#路线图)

> 📖 **完整用户手册**：[docs/manual.md](docs/manual.md)（英文）—— 按任务组织
> 的全功能指南：发布、在线编辑、权限、数据、安全、身份登录、迁移、FAQ。

## 为什么选 html-golive

- **一条命令，一个 URL。** 不用构建、不用写服务端、不用云账号。
  `golive publish` → 直接分享链接。
- **一切皆单文件。** 目录和压缩包自动打包——CSS/JS 内联、图片压缩内嵌
  （或走你自己的图床上传）。
- **静态页面，真实数据。** 纯 HTML 页面通过 `window.TemplateAPI` /
  `window.SupabaseAPI` 读写真实数据库，零服务端代码。
- **技术栈完全自主。** 全部跑在你自己的基础设施上，发布/托管时零外呼
  （[详情](#网络行为)）。
- **生产习惯内建。** 短域名冲突校验、10 快照回滚、每次发布凭证/隐私
  扫描、审计日志。

## 快速开始

### 1 · 安装

```bash
pip install html-golive              # 核心
pip install 'html-golive[image]'     # + 图片压缩（Pillow）
pip install 'html-golive[s3]'        # + S3 兼容后端（boto3）
```

### 2 · 发布

```bash
golive publish index.html --name Demo --slug demo
golive publish ./my-project/ --slug app      # 目录 → 打包为单 HTML
golive publish site.zip                      # zip / tar.gz 同样支持
golive publish page.html --style apple       # 套用 19 种 CSS 风格之一
```

### 3 · 启动服务

```bash
golive serve --port 8787
# → http://<你的主机>:8787/demo
```

### 日常命令

```bash
golive list                                  # 所有已发布站点
golive publish new.html --update demo        # 覆盖更新
golive rollback demo --dry-run               # 查看快照，确认后 --yes
golive preview draft.html                    # 热更新预览 + 风格面板
golive clone https://example.com --save-only # 克隆公网页面
golive styles                                # 查看 19 种 CSS 风格
golive doctor                                # 环境体检
golive skill install                         # 让 AI agent 学会正确使用 golive

# v0.3 —— 在线编辑与水印
golive publish page.html --enable-editor --owner you@example.com
golive maintainer add demo teammate@example.com
golive publish page.html --watermark "内部资料"
```

### 在线编辑（v0.3）

```bash
export GOLIVE_EDITOR_TOKEN=$(openssl rand -hex 16)
golive publish report.html --slug q3 --enable-editor --owner you@example.com
golive serve
# 打开 http://localhost:8787/q3?editor_token=<token>&editor_user=you@example.com
# 点右下角 ✏️ → 直接改文字 → 💾 保存（自动先打快照）
```

保存走与发布完全相同的安全扫描管线，只有站点 owner 和 maintainer
能改，每次覆盖前自动生成回滚快照。配置 `auth.provider: oidc` 后，
编辑器直接认登录会话，无需 token 参数。

## 功能

**发布与内容**
- 单 HTML / 目录 / zip / tar.gz 发布，资源自动打包
- 19 种内置 CSS 美化风格（`--style`，`GOLIVE_FONT_CDN_BASE`
  自定义字体源）
- 图片压缩（`--compress`）+ 可插拔图床（`GOLIVE_UPLOADER_CMD`
  命令模板，或原生 S3 上传器）
- 网页克隆（`golive clone <url>`），支持静态快照模式

**运维**
- 短域名保留字 + 占用双重校验
- 每站点 10 份快照回滚
- 内置静态服务，带 JSON API 与健康检查端点
- 热更新实时预览 + 风格切换面板
- `golive doctor` 环境诊断、审计日志

**数据与后端** *(v0.2；SQLite 数据层 v0.7)*
- `window.TemplateAPI` / `window.SupabaseAPI` 注入——静态页面零服务端
  代码获得真实数据库
- 三层后端各自独立切换：
  - **storage**（站点 HTML）：`local`（默认）/ `s3` / `supabase`
  - **registry**（站点元信息）：`sqlite`（默认）/ `supabase`
  - **data**（TemplateAPI 数据行）：`sqlite`（默认）/ `supabase` /
    `none`
  默认三层全本地——SQLite 文件落在 `GOLIVE_HOME` 下，无需注册任何服务；
  需要多机共享时，一个 Supabase 项目可以同时承载三层。
- `golive migrate-check` —— 从其他 golive 部署迁移页面
- Docker Compose 部署（含可选 MinIO profile）

**编辑、身份与水印** *(v0.3)*
- 浏览器在线编辑器（`publish --enable-editor`）：contenteditable 文字
  编辑，保存 API 复跑完整安全管线、覆盖前先打快照、owner/maintainer
  权限控制（`golive maintainer add/remove/list`）
- 页面水印（`--watermark [文本]`）：canvas 平铺身份水印——OIDC 用户 /
  静态文本 / 页面 meta 标签三选一；可选访问上报 webhook；
  `GOLIVE_WATERMARK_OFF=1` 全局禁用
- 通用 **OIDC 登录**（`auth.provider: oidc`）：Google / Keycloak /
  Authentik 等任意带 discovery 文档的 IdP；PKCE + 签名会话 cookie；
  管理 API 与编辑器 API 均认会话
- 可选 **LLM 安全复核**：弱命中送任意 OpenAI 兼容端点二次判定
  （`security.llm.*`），失败保守降级，支持 `strict_mode` 硬门槛

**运营管理门户** *(v0.5)*
- `/admin` Web 管理门户：站点列表/搜索、基本信息编辑、maintainer 与
  owner 移交管理、快照回滚、输入 slug 确认删除——按角色隔离
  （owner / maintainer / 超管，超管名单来自 `admin.admins` 或
  `GOLIVE_ADMINS`）；超管另有统计看板与审计日志页；全部操作
  也可通过 `/api/admin/*` JSON API 脚本化调用

**AI agent skill** *(v0.7)*
- `golive skill install` 把随包分发的 AgentSkill 装进 agent 的 skills
  目录（自动探测位置）：教它先探测环境再动手、按 slug 更新而不是重复
  发布、正确接入 `TemplateAPI`，并明确区分「本地自部署 CLI」与任何同名
  的托管服务
- skill 打在 wheel 里，离线可装；`golive skill status` 提示版本漂移

**安全**
- 每次发布凭证/隐私信息扫描（YAML 可扩展规则）
- 服务端与压缩包解压均做路径穿越防护
- 管理 API token 保护（`GOLIVE_TOKEN`）

## 架构

```
┌────────────── golive core（纯逻辑） ──────────────────────┐
│ 打包 / 图片压缩 / CSS 风格 / 克隆 / 预览 /                │
│ 安全扫描 / 短域名校验                                     │
└──────┬──────────────────┬──────────────────┬──────────────┘
  StorageBackend    RegistryBackend     DataBackend
  站点 HTML/资源     站点元信息          TemplateAPI/SupabaseAPI
       │                  │                  │
  local-fs / s3 /    sqlite / supabase   sqlite（本地文件）/
  supabase storage                       supabase (PostgREST) / none
       │
  AuthProvider: none（默认）/ token（GOLIVE_TOKEN）/ oidc（通用 OIDC）
```

所有数据存放在 `GOLIVE_HOME`（默认 `~/.golive/`）：

```
~/.golive/
├── sites/<site_id>/index.html   已发布内容
├── backups/<site_id>/           回滚快照（最多 10 份）
├── registry.db                  SQLite 注册表 + 可管理超管名单
├── data.db                      SQLite 数据层（TemplateAPI 数据行）
├── audit.log                    管理操作审计流水
├── logs/                        运行日志
└── cache/                       风格备份等缓存
```

默认后端下，以上 SQLite 文件与目录就是全部持久化——不依赖任何外部服务。
使用 `TemplateAPI` 的页面通过 `golive serve` 的 `/api/data` 端点读写
`data.db`，因此页面必须由服务端访问，直接以 `file://` 打开无效。
详见 [docs/data-layer.md](docs/data-layer.md)。

## 配置

零配置即可使用。两层配置，**环境变量永远覆盖 yaml**：

### golive.yaml（后端选型）

查找顺序：`--config <path>` → `$GOLIVE_CONFIG` → `./golive.yaml` →
`$GOLIVE_HOME/golive.yaml`。完整注释样例：
[golive.example.yaml](golive.example.yaml) · 后端组合实例：
[docs/backends.md](docs/backends.md)

### 环境变量

| 变量 | 用途 |
|---|---|
| `GOLIVE_HOME` | 数据目录（默认 `~/.golive/`） |
| `GOLIVE_TOKEN` | 保护 `/api/sites`（Bearer 或 `X-Golive-Token`） |
| `GOLIVE_EDITOR_TOKEN` | 在线编辑器保存令牌（未设则回落 `GOLIVE_TOKEN`） |
| `GOLIVE_WATERMARK_TEXT` / `GOLIVE_WATERMARK_OFF` | 水印文本 / 全局禁用开关 |
| `GOLIVE_OIDC_CLIENT_SECRET` / `GOLIVE_COOKIE_SECRET` | OIDC client secret / 会话 cookie HMAC 密钥 |
| `GOLIVE_LLM_BASE_URL` / `GOLIVE_LLM_MODEL` / `GOLIVE_LLM_API_KEY` | LLM 安全复核端点 |
| `GOLIVE_FONT_CDN_BASE` | 替换 `fonts.googleapis.com` 为自有字体镜像 |
| `GOLIVE_UPLOADER_CMD` | 图片上传命令模板（`mytool up {file}`） |
| `GOLIVE_SUPABASE_URL` / `_ANON_KEY` / `_SERVICE_KEY` | Supabase 后端 |
| `GOLIVE_S3_AK` / `GOLIVE_S3_SK` | S3 兼容后端 |
| `FIRECRAWL_API_KEY` | `golive clone` 重 JS 页面的可选降级通道 |

### 网络行为

golive 在发布/托管时**不产生任何外呼**。例外：`golive clone <url>`
抓取目标页面；`golive preview` 首次运行从 `cdn.tailwindcss.com` 下载
一次性 Tailwind 缓存（离线时静默降级）；注入的 CSS 风格引用公网字体
CDN（可用 `GOLIVE_FONT_CDN_BASE` 替换）；以及你自己配置的图床命令
与后端。

## 数据层：给静态页面一个数据库

接上你自己的 Supabase 项目即可，无需写服务端：

```bash
golive db init --print-sql              # 建表 SQL 粘到 Supabase SQL Editor
golive publish app.html --data-model myapp_v1
```

页面里直接调用：

```js
// 命名空间化记录存储
await TemplateAPI.upsert({ templateName: 'vote:alice', templateContent: {n: 1} });
const { total, list } = await TemplateAPI.listAll();

// 或直连表操作
const { rows } = await SupabaseAPI.query('feedback', { limit: 50 });
```

API 签名是**稳定契约**——在任何 golive 部署上开发的页面，换个部署零改
动可跑。完整指南（含 RLS 安全须知）：[docs/data-layer.md](docs/data-layer.md)。

> **说明**：未配置 data backend 时 `--data-model` 发布依然成功——页面
> 注入的是 stub API，调用时报清晰的"data backend 未配置"错误（发布时
> 也会打印警告提示）。

从其他部署迁移页面？先跑 `golive migrate-check page.html`，它会报告
所有部署专属引用（[迁移指南](docs/migrate-from-intranet.md)）。

## 安全扫描

每次发布都按内置规则扫描——API key、私钥、数据库连接串、个人信息等。
强特征命中直接阻断发布；弱特征命中仅告警——还可以选配任意 OpenAI 兼容
LLM 做语义二次判定（`security.llm.base_url`，OpenAI / Azure / Ollama /
自建网关均可）。未配置时维持纯规则判定；`strict_mode: true` 则"没有 AI
复核不发布"。可用自己的 YAML 扩展规则，确认误报时 `--skip-scan` 跳过。
详见 [docs/security.md](docs/security.md)

## Docker

```bash
docker compose up -d golive                 # golive serve 跑在 :8787
docker compose --profile minio up -d        # 加本地 S3（图床用）
```

## 路线图

- ~~**M1 — 内核**：发布/托管/回滚、风格、克隆、预览、安全扫描~~ ✅ v0.1
- ~~**M2 — 数据层**：Supabase 后端三件套、TemplateAPI/SupabaseAPI 注入、
  S3 适配器、migrate-check、Docker Compose~~ ✅ v0.2
- ~~**M3 — 编辑与身份**：在线编辑器（版本化保存 API）、水印、OpenAI 兼容
  LLM 安全复核、通用 OIDC~~ ✅ v0.3
- ~~**M4 — 文档与打磨**：OIDC 常见 IdP 快捷预设、编辑器图片上传、cookie
  密钥持久化、完整用户手册~~ ✅ v0.4
- ~~**M5 — 运营管理门户**：`/admin` 网页控制台、三级角色（超管 / 站点
  owner / maintainer）、所有权移交、审计日志~~ ✅ v0.5
- ~~**M6 — 数据管理**：门户内数据管理页、审计日志轮转~~ ✅ v0.6
- **下一步**：数据批量导入导出、超大表聚合优化、共享会话存储（redis）、
  多人编辑冲突体验、基于组的权限。

## 参与贡献

欢迎提 issue 和 PR——开发环境搭建、代码约定、以及怎样算一份好的缺陷报告，
都写在 [CONTRIBUTING.md](CONTRIBUTING.md) 里。整套测试离线即可运行，不需要
任何云账号：

```bash
pip install -e '.[image,dev]'
python -m pytest tests/ -q
```

## 许可证

[MIT](LICENSE) © 2026 Songhonglei

---

English documentation: [README.md](README.md).
