# WorkBuddy / 其他 Agent：MySQL 安装、初始化与验证

适用版本：html-golive **v0.9.7**；数据库：**MySQL 8.4+**。这是一套本机自部署工具，不需要 golive 平台账号。Python 的 MySQL extra 安装驱动，不会自动安装数据库服务。

WorkBuddy 官方支持[项目级 `.codebuddy/skills`](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Project)，也可在[技能界面上传本地技能包](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market)。请使用真实受支持的入口，不要猜测 `~/.workbuddy` 等安装目录。

## 安装 Skill 的两种方式

- **项目级（推荐验证使用）**：在 WorkBuddy 中打开一个独立项目，创建 Python 虚拟环境并安装 `html-golive[mysql]==0.9.7`，然后运行 `golive skill install --target .codebuddy/skills`。重新打开项目任务，确认读取到 `html-golive v0.9.7`。这里 `golive` 必须来自该虚拟环境。
- **界面导入**：从 [v0.9.7 Release](https://github.com/Songhonglei/html-golive/releases/tag/v0.9.7) 下载 `html-golive-skill-0.9.7.zip`，在 WorkBuddy 的“技能 → 添加技能 → 上传技能”导入并启用。仍需在 agent 实际执行命令的环境中安装同版本 Python 包和 MySQL 驱动。

其他 Agent 使用 `golive skill install --target <实际 skills 父目录>`。CLI 不负责证明第三方 Agent 已加载技能；需在该 Agent 里确认名称与版本。

## 直接复制给 WorkBuddy

```text
请安装并验收 html-golive v0.9.7，数据库必须使用真实 MySQL 8.4+。
项目：https://github.com/Songhonglei/html-golive
完整操作手册：https://github.com/Songhonglei/html-golive/blob/main/golive/resources/skill/references/mysql.md

请直接执行下列步骤，使用独立项目目录，不改现有业务环境：

1. 探测操作系统、Python、pip、Docker、端口及已有 golive。创建项目虚拟环境，
   用该环境的 Python 安装 'html-golive[mysql]==0.9.7'，确认 CLI 版本。
   全程使用同一虚拟环境；Windows 使用 Scripts 路径，macOS/Linux 使用 bin 路径。

2. 在项目根目录运行 golive skill install --target .codebuddy/skills，
   用 golive skill status 检查版本。重新加载项目并读取 html-golive 的 SKILL.md
   和 references/mysql.md，确认 agent 实际加载了 v0.9.7。
   已有同名旧 Skill 时备份后用 --force 更新。

3. 优先使用我已授权的专用 MySQL 测试连接。若没有且 Docker 可用，创建隔离的
   mysql:8.4 容器、专用库/用户和新数据卷，端口仅绑定 127.0.0.1。
   密码随机生成，通过受保护的本机文件或环境变量保存，不在回复/日志中回显。
   没有 Docker 或可用数据库时，再集中询问连接信息和本机凭证文件路径。
   禁止以 SQLite、mock 或“连接成功”代替 MySQL 完整验收。

4. 在独立 GOLIVE_HOME 下创建 golive.yaml：storage.backend=local，
   registry.backend=mysql，registry.mysql.dsn_env=GOLIVE_MYSQL_DSN，
   data.backend=mysql，data.templates_table=golive_templates，
   server.host=127.0.0.1，server.port=8788（占用则另选空闲端口）。
   设置绝对路径 GOLIVE_HOME、GOLIVE_CONFIG 和 GOLIVE_MYSQL_DSN；密码做 URL 编码。
   每次 CLI 调用和后台服务启动都必须继承相同环境。

5. 依次执行 golive db init、golive context、
   golive serve start --host 127.0.0.1 --port <端口>、
   golive doctor --port <端口> --json、golive verify --json。
   确认 registry/data 都是 mysql，CLI/Skill/运行服务均为 0.9.7，verify 返回 ok:true。

6. 使用唯一测试 model 完成 CLI 的 create/list/get/update/upsert/delete；
   数据包含中文、emoji 和嵌套 JSON。创建一个调用 TemplateAPI 的 HTML 页面，
   通过 --data-model 发布并在真实浏览器执行创建、读取、修改、upsert、排序、分页、删除。
   刷新页面、重启这个测试服务后，保留的测试数据必须仍存在。
   检查 /admin 的数据记录和 MySQL 连接测试，确认探针回滚、不遗留额外记录。

7. 使用同一 DSN 直接查询 MySQL 的 VERSION()、DATABASE() 和测试 model 的记录，
   证明浏览器写入实际进入 MySQL。不要只依据页面提示或 HTTP 200 判断通过。
   不运行会清表的仓库测试；只操作本次专用库和测试数据。

8. 交付实际版本、命令路径、后端配置（脱敏）、页面和后台 URL、各项验收结果及 SQL 证据。
   浏览器不可用时明确标为待验证；失败/跳过也必须说明，不得用其他后端兜底后报成功。
   保留测试页面、服务和专用数据库供我检查，并提供准确的停止/清理命令。
```

完整配置、权限、TLS、示例 SQL 与验收口径随 Skill 一起分发，见 [MySQL 操作手册](https://github.com/Songhonglei/html-golive/blob/main/golive/resources/skill/references/mysql.md)。四后端验证方法见[后端指南](backend-validation.md)，上一轮真实数据库结果见[验收记录](validation-four-backends.md)。
