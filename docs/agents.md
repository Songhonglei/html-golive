# Use html-golive with your agent

html-golive exposes the same CLI and bundled AgentSkill to different agents.
Choose an agent that can run local commands, and install the skill into a
directory that agent actually reads. The product is not tied to one client.

中文：使用支持本机命令执行的 Agent，并将随包 Skill 安装到它实际读取的目录。
发布、回滚、安全扫描、站点权限与四种数据库能力沿用同一套 CLI。

## Install the CLI and skill

Create a Python 3.9+ virtual environment in your project and activate it. Then:

```bash
python -m pip install 'html-golive==0.9.7.post1'
golive --version
golive skill install --list-targets
golive skill install
golive skill status
```

The installer detects common project and user skill locations, including
Codex, Claude Code, Cursor and CodeBuddy / WorkBuddy conventions. Check its
reported destination. For another layout, pass your agent's actual **skills
parent directory** explicitly:

```text
golive skill install --target <your-agent-skills-directory>
```

The resulting file is `<your-agent-skills-directory>/html-golive/SKILL.md`.
Reload the project or task, then confirm the agent has read that skill and
its version matches the CLI. `skill status` checks files; the agent must
separately confirm it loaded them. To replace an old installed copy, add
`--force`; the installer backs up the previous copy.

## Give your agent a first task

Copy this request and replace the source file and slug:

```text
Use the installed html-golive skill to publish ./report.html as report.
Probe the installed CLI version, effective context, doctor output and existing
sites first. Use an isolated GOLIVE_HOME for a new test project and the same
Python environment for every command. If report already exists, update that
site rather than creating a duplicate.

Run the normal security scan; do not waive credential findings. Start a local
listener on 127.0.0.1 and an available port. Verify the resulting page in a real
browser, and return its URL, the /admin URL and the actual validation results.
If something cannot be verified, say which step remains pending.
```

The default setup uses local files and SQLite. Typical commands are:

```bash
golive context
golive doctor
golive list
golive publish report.html --slug report
golive serve start --host 127.0.0.1 --port 8787
golive verify --json
```

Run commands in the project environment with the same `GOLIVE_HOME` and
configuration. `verify` performs real HTTP and database probes, and cleans
up its temporary page and records. It does not replace a browser check.

## Add data or collaboration

- **Four databases:** [SQLite / PostgreSQL / MySQL / Supabase setup and acceptance](backend-validation.md).
- **MySQL:** install `html-golive[mysql]==0.9.7.post1`, then follow the bundled [MySQL runbook](../golive/resources/skill/references/mysql.md). Its database configuration and acceptance steps apply across agents; adapt the skill installation directory to yours.
- **PostgreSQL:** install `html-golive[postgres]==0.9.7.post1` and configure the dedicated server-side DSN as described in the backend guide.
- **Security:** [scanning, blocking rules and optional LLM review](security.md).
- **Collaboration:** [site owners, maintainers and management roles](manual.md#7-access-control), with [admin permissions and audit](manual.md#18-admin-portal).

Client-specific examples, such as [WorkBuddy with MySQL](workbuddy-mysql.md),
are optional adaptations of this workflow, not product requirements.
