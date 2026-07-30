# Upgrading html-golive

*[中文版在下方](#升级-html-golive中文)*

Three things to know before you upgrade:

1. **Upgrading the code does not upgrade a running server.** `golive serve`
   holds the old code in memory until you restart it. This is the single
   most common "I updated but nothing changed" report.
2. **`golive doctor` tells you whether you actually upgraded.** It prints
   the CLI version and the version of the service currently answering on
   the port, and complains when they differ.
3. **If you cloned the repo before v0.7.0, `git pull` will fail.** We
   force-pushed `main` during that release and rewrote history. See
   [Recovering from the v0.7.0 history rewrite](#recovering-from-the-v070-history-rewrite).

---

## If you installed from PyPI

```bash
pip install -U html-golive
```

Confirm which version you now have:

```bash
golive --version          # → golive 0.7.1
```

If a server was already running, it is still running the **old** code.
Restart it:

```bash
golive serve restart      # background service (v0.7.1+)
```

or, if you started it in the foreground, press `Ctrl+C` in that terminal
and run `golive serve` again.

Then verify:

```bash
golive doctor
```

`doctor` prints both versions on the first two lines. They must match:

```
golive           0.7.1                          (CLI)
running service  0.7.1  pid 12345  port 8787    ✅
```

If you see `⚠️ version mismatch`, the restart did not take — find the
stale process with `golive serve status` and stop it with
`golive serve stop`.

### Installed with pipx / uv / a virtualenv?

```bash
pipx upgrade html-golive
uv tool upgrade html-golive
# or inside an activated venv:
pip install -U html-golive
```

Then restart the server and run `golive doctor` exactly as above.

---

## If you cloned the git repo

### Normal case

```bash
cd html-golive
git pull --ff-only
pip install -e '.[image,dev]'
golive serve restart
golive doctor
```

`--ff-only` is deliberate: it refuses to create a surprise merge commit,
and it fails loudly if your local branch has diverged — which is exactly
what you want to know about.

### Recovering from the v0.7.0 history rewrite

**What happened:** when v0.7.0 was released, `main` was force-pushed and
the commit history was rewritten. Every clone made before that release
now has a `main` whose commits no longer exist upstream. `git pull`
reports something like:

```
fatal: refusing to merge unrelated histories
```

or

```
 ! [rejected]        main -> main (non-fast-forward)
```

This was our mistake, not yours. Force pushes to `main` are now blocked
at the repository level (`allow_force_pushes: false`), so this will not
happen again.

**Recovery — no local changes you care about:**

```bash
cd html-golive
git fetch origin
git reset --hard origin/main
pip install -e '.[image,dev]'
golive serve restart
golive doctor
```

`git reset --hard` throws away uncommitted work in the working tree. Use
the next recipe if you have any.

**Recovery — you have local changes to keep:**

```bash
cd html-golive

# 1. keep a full escape hatch: your current main, under a new name
git branch backup-before-v070-recovery

# 2. park uncommitted work
git stash push -u -m "pre-upgrade local changes"

# 3. re-point main at the rewritten upstream history
git fetch origin
git reset --hard origin/main

# 4. bring your work back (resolve conflicts if any)
git stash pop

pip install -e '.[image,dev]'
golive serve restart
golive doctor
```

Your old commits are still reachable on `backup-before-v070-recovery`.
To move a specific commit onto the new history:

```bash
git cherry-pick <sha-from-backup-branch>
```

Once you are satisfied, delete the safety branch:

```bash
git branch -D backup-before-v070-recovery
```

**Recovery — simplest option:** if you have nothing local to keep, a
fresh clone is faster than any of the above.

```bash
mv html-golive html-golive-old
git clone https://github.com/Songhonglei/html-golive.git
cd html-golive && pip install -e '.[image,dev]'
```

Your published sites and databases are **not** in the repo — they live in
`GOLIVE_HOME` (`~/.golive/` by default), so re-cloning loses nothing.

---

## Behaviour changes by version

### 0.6.x → 0.7.0 — the data layer defaults to SQLite

Before 0.7.0, `window.TemplateAPI` needed a configured Supabase project;
without one, publishing a page that used it injected a stub that failed
at runtime.

From 0.7.0 the default is `data.backend: sqlite`. Rows live in
`$GOLIVE_HOME/data.db`, and pages reach them through the
`/api/data/<table>` endpoint served by `golive serve`.

What this means for you:

- **You configured Supabase explicitly** (`data.backend: supabase` in
  `golive.yaml`): nothing changes, your config still wins.
- **You configured nothing** and relied on the data layer being off:
  it is now **on**. Pages using `TemplateAPI` will start reading and
  writing `data.db` instead of failing. Set `data.backend: none` to
  restore the old behaviour.
- **Pages opened over `file://` still do not work** with the sqlite
  backend — there is no server to talk to. Open them through
  `golive serve`.
- **`golive db init` is no longer required** for local backends; tables
  are created on first access.

Check which backend you are actually on:

```bash
golive doctor
# data backend    sqlite → /home/you/.golive/data.db  (3 tables, 47 rows)
```

### 0.7.0 → 0.7.1 — background service, no breaking changes

`golive serve` with no sub-action still runs in the **foreground** exactly
as before. v0.7.1 only *adds* sub-actions:

```bash
golive serve start      # background, pidfile + log file
golive serve status
golive serve stop
golive serve restart
golive serve logs -n 50 -f
```

Nothing you have scripted against `golive serve` needs to change.

---

## Rolling back an upgrade

```bash
pip install 'html-golive==0.7.0'
golive serve restart
```

`GOLIVE_HOME` is forward-compatible within the 0.x line: schema changes
are additive, so downgrading the code does not corrupt an existing
`registry.db` or `data.db`. Back the directory up anyway before any
upgrade you are nervous about:

```bash
cp -a ~/.golive ~/.golive.bak-$(date +%F)
```

---

## Upgrade checklist

```bash
golive --version                # 1. new version installed?
golive serve restart            # 2. service actually restarted?
golive doctor                   # 3. CLI and service agree? backends healthy?
golive skill install --force    # 4. (if you use the agent skill) resync it
```

---
---

# 升级 html-golive（中文）

升级前需要知道三件事：

1. **升级代码不会升级正在运行的服务。** `golive serve` 会一直用内存里的
   旧代码，直到你重启它。「我明明更新了但行为没变」几乎都是这个原因。
2. **`golive doctor` 会告诉你到底升没升上去。** 它同时打印 CLI 版本和
   当前占用端口的服务版本，两者不一致时会直接报警。
3. **如果你在 v0.7.0 之前 clone 过仓库，`git pull` 会失败。** 那次发布时
   我们 force push 重写了 `main` 的历史，见
   [从 v0.7.0 历史重写中恢复](#从-v070-历史重写中恢复)。

---

## PyPI 安装的用户

```bash
pip install -U html-golive
```

确认版本：

```bash
golive --version          # → golive 0.7.1
```

如果服务已经在跑，它跑的还是**旧代码**。重启：

```bash
golive serve restart      # 后台服务（v0.7.1 起）
```

如果当初是前台起的，在那个终端按 `Ctrl+C`，再 `golive serve`。

然后验证：

```bash
golive doctor
```

`doctor` 前两行会把两个版本并排打出来，必须一致：

```
golive           0.7.1                          (CLI)
running service  0.7.1  pid 12345  port 8787    ✅
```

如果看到 `⚠️ 版本不一致`，说明重启没生效——用 `golive serve status`
找到残留进程，`golive serve stop` 停掉。

### 用 pipx / uv / 虚拟环境装的？

```bash
pipx upgrade html-golive
uv tool upgrade html-golive
# 或在激活的 venv 里：
pip install -U html-golive
```

之后同样要重启服务并跑 `golive doctor`。

---

## git clone 的用户

### 正常情况

```bash
cd html-golive
git pull --ff-only
pip install -e '.[image,dev]'
golive serve restart
golive doctor
```

用 `--ff-only` 是有意的：它拒绝生成意外的 merge commit，一旦本地分支和
远端分叉就直接报错——这正是你需要立刻知道的事。

### 从 v0.7.0 历史重写中恢复

**发生了什么：** v0.7.0 发布时，`main` 被 force push，提交历史被重写。
所有在那之前 clone 的仓库，本地 `main` 上的 commit 在远端已经不存在了。
`git pull` 会报：

```
fatal: refusing to merge unrelated histories
```

或者：

```
 ! [rejected]        main -> main (non-fast-forward)
```

这是我们的失误，不是你的操作问题。现在仓库层面已经关掉了 `main` 的
force push（`allow_force_pushes: false`），不会再发生。

**恢复方式一——本地没有要保留的改动：**

```bash
cd html-golive
git fetch origin
git reset --hard origin/main
pip install -e '.[image,dev]'
golive serve restart
golive doctor
```

`git reset --hard` 会丢掉工作区里未提交的内容。有改动要留就走下面这套。

**恢复方式二——本地有改动要保住：**

```bash
cd html-golive

# 1. 先留一条后路：把当前 main 另存一个分支
git branch backup-before-v070-recovery

# 2. 把未提交的改动暂存起来
git stash push -u -m "升级前的本地改动"

# 3. 让 main 指向重写后的远端历史
git fetch origin
git reset --hard origin/main

# 4. 把改动放回来（有冲突就解冲突）
git stash pop

pip install -e '.[image,dev]'
golive serve restart
golive doctor
```

你原来的提交都还在 `backup-before-v070-recovery` 分支上。想把其中某个
提交搬到新历史上：

```bash
git cherry-pick <备份分支上的-sha>
```

确认没问题之后删掉这条保险分支：

```bash
git branch -D backup-before-v070-recovery
```

**恢复方式三——最省事：** 本地没有要保留的东西，重新 clone 比上面任何
一种都快。

```bash
mv html-golive html-golive-old
git clone https://github.com/Songhonglei/html-golive.git
cd html-golive && pip install -e '.[image,dev]'
```

你发布的站点和数据库**不在仓库里**，它们在 `GOLIVE_HOME`
（默认 `~/.golive/`），重新 clone 不会丢任何数据。

---

## 各版本的行为变化

### 0.6.x → 0.7.0 —— 数据层默认改成 SQLite

0.7.0 之前，`window.TemplateAPI` 必须先配好 Supabase；没配的话发布会注入
一个 stub，页面运行时调用就报错。

从 0.7.0 起默认值是 `data.backend: sqlite`。数据存在
`$GOLIVE_HOME/data.db`，页面通过 `golive serve` 提供的
`/api/data/<table>` 接口读写。

对你意味着什么：

- **你显式配了 Supabase**（`golive.yaml` 里 `data.backend: supabase`）：
  什么都不变，你的配置优先。
- **你什么都没配**，并且默认数据层是关着的：现在它**开了**。用了
  `TemplateAPI` 的页面会开始真的读写 `data.db`，而不是报错。想恢复旧
  行为，设 `data.backend: none`。
- **用 `file://` 直接打开的页面在 sqlite 后端下仍然不工作**——没有服务
  可以对话。请通过 `golive serve` 访问。
- **本地后端不再需要 `golive db init`**，表在首次访问时自动创建。

确认自己实际用的是哪个后端：

```bash
golive doctor
# data backend    sqlite → /home/you/.golive/data.db  (3 tables, 47 rows)
```

### 0.7.0 → 0.7.1 —— 新增后台服务，无破坏性变更

不带子动作的 `golive serve` 依然是**前台**运行，行为和以前完全一样。
v0.7.1 只是*新增*了子动作：

```bash
golive serve start      # 后台运行，写 pidfile 和日志文件
golive serve status
golive serve stop
golive serve restart
golive serve logs -n 50 -f
```

你已有的、基于 `golive serve` 写的脚本不需要改动。

---

## 回退升级

```bash
pip install 'html-golive==0.7.0'
golive serve restart
```

`GOLIVE_HOME` 在 0.x 线内向前兼容：schema 变更都是增量的，降级代码不会
破坏已有的 `registry.db` 或 `data.db`。不放心的升级前照样先备份：

```bash
cp -a ~/.golive ~/.golive.bak-$(date +%F)
```

---

## 升级检查清单

```bash
golive --version                # 1. 新版本装上了吗？
golive serve restart            # 2. 服务真的重启了吗？
golive doctor                   # 3. CLI 和服务版本一致吗？后端健康吗？
golive skill install --force    # 4. （用了 agent skill 的话）同步一下
```
