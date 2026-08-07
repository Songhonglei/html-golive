"""golive.core.skill_installer — install the bundled agent skill.

golive ships an AgentSkill (``golive/resources/skill/``) that teaches an
AI coding assistant how to drive the local ``golive`` CLI: probe the
environment first, publish/update/roll back, wire up the data layer, and
avoid confusing golive with any similarly named hosted service.

``golive skill install`` copies that directory into the agent's skills
folder. Targets are auto-detected from a table of common conventions
(project-local first, then user-level) — and, crucially, ranked by
*which agent is actually installed on this machine*, so a Codex user
doesn't get the skill quietly dropped into ``~/.claude/skills`` where
nothing will ever read it. Unknown setups are handled by ``--target``.

Public API:
  packaged_skill_dir()      -> Path of the skill shipped inside the wheel
  read_skill_meta(dir)      -> {name, version, description} from frontmatter
  detect_targets()          -> [Candidate, ...] ranked, best first
  viable_targets()          -> candidates we would actually install into
  choose_target()           -> (Path, how) with an interactive menu
  install(...)              -> dict describing what happened
  status()                  -> installed-vs-current version comparison
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

SKILL_NAME = "html-golive"
GITHUB_REPO = "Songhonglei/html-golive"
GITHUB_TARBALL = f"https://github.com/{GITHUB_REPO}/archive/refs/heads/main.tar.gz"

#: Where agents keep skills. Ordered: project-local beats user-level, and
#: within each tier the more specific convention comes first. Extend this
#: table rather than adding conditionals elsewhere.
#:
#: The 4th column is the *agent marker*: the directory whose presence proves
#: that agent is actually installed on this machine. Detection ranks
#: candidates whose marker exists above ones that merely follow a
#: convention, because "golive installed the skill somewhere your agent
#: never looks" is the single most wasted install (a Codex user got the
#: skill dropped into ~/.claude/skills and nothing happened).
TARGET_CONVENTIONS = (
    # (relative-to, path template, label, agent marker relative to the root)
    ("cwd",  ".codex/skills",            "project skills directory", ".codex"),
    ("cwd",  ".claude/skills",           "project skills directory", ".claude"),
    ("cwd",  ".cursor/skills",           "project skills directory", ".cursor"),
    ("cwd",  ".agent/skills",            "project skills directory", ".agent"),
    ("cwd",  ".config/agent/skills",     "project skills directory", ".config/agent"),
    ("cwd",  "skills",                   "project skills directory", "skills"),
    ("home", ".codex/skills",            "user skills directory",    ".codex"),
    ("home", ".claude/skills",           "user skills directory",    ".claude"),
    ("home", ".cursor/skills",           "user skills directory",    ".cursor"),
    ("home", ".agent/skills",            "user skills directory",    ".agent"),
    ("home", ".config/agent/skills",     "user skills directory",    ".config/agent"),
    ("home", ".local/share/agent/skills", "user skills directory",   ".local/share/agent"),
)

#: Marker directory -> product name, for human-readable menus.
AGENT_NAMES = {
    ".codex": "Codex",
    ".claude": "Claude Code",
    ".cursor": "Cursor",
    ".agent": "generic agent",
    ".config/agent": "generic agent (XDG)",
    ".local/share/agent": "generic agent (XDG data)",
    "skills": "plain ./skills",
}

#: Files copied into the target (everything else is ignored).
_COPY_SUFFIXES = (".md", ".txt", ".json", ".yaml", ".yml", ".py", ".sh")


class SkillInstallError(RuntimeError):
    """Raised for anything the caller should see as a clean CLI error."""


class NoAgentDetected(SkillInstallError):
    """Raised when no AI agent directory is found on this machine.

    This is *not* an error — many users have no AI agent installed.
    Callers (especially ``init_wizard._step_skill``) should catch this
    separately and treat it as a neutral skip rather than a failure.

    The message is phrased as guidance, not an error:

        ⊘ agent skill：未检测到 AI agent
           （需要时运行 golive skill install）
    """


class Candidate:
    """One possible install location.

    ``exists``       — the skills directory itself is already there.
    ``agent_present``— the agent's own directory (``~/.codex``, ``~/.claude``…)
                       is there, so the skills dir would be picked up if we
                       created it.
    ``installed``    — this location already holds an html-golive skill.
    """

    __slots__ = ("path", "label", "exists", "marker", "agent_present",
                 "agent", "scope")

    def __init__(self, path: Path, label: str, marker: str = "",
                 marker_path: Optional[Path] = None, scope: str = ""):
        self.path = path
        self.label = label
        self.marker = marker
        self.scope = scope
        self.agent = AGENT_NAMES.get(marker, marker or "unknown")
        self.exists = path.is_dir()
        self.agent_present = bool(marker_path and marker_path.is_dir())

    @property
    def installed(self) -> bool:
        return (self.path / SKILL_NAME / "SKILL.md").is_file()

    def describe(self) -> str:
        """One-line human summary used by menus and ``--list-targets``."""
        flags = []
        if self.exists:
            flags.append("skills dir exists")
        elif self.agent_present:
            flags.append("agent detected, skills dir would be created")
        else:
            flags.append("not present")
        if self.installed:
            flags.append("html-golive already installed")
        return f"{self.path}  [{self.agent}] ({'; '.join(flags)})"

    def as_dict(self) -> dict:
        return {
            "path": str(self.path),
            "agent": self.agent,
            "marker": self.marker,
            "scope": self.scope,
            "label": self.label,
            "exists": self.exists,
            "agent_present": self.agent_present,
            "installed": self.installed,
        }

    def __repr__(self):  # pragma: no cover — debugging aid
        return (f"<Candidate {self.path} exists={self.exists} "
                f"agent_present={self.agent_present}>")


# ── packaged skill ───────────────────────────────────────────────────────────

def packaged_skill_dir() -> Path:
    """Absolute path of the skill directory shipped inside the package."""
    return Path(__file__).resolve().parent.parent / "resources" / "skill"


def _parse_frontmatter(text: str) -> dict:
    """Minimal YAML frontmatter reader (top-level scalars only).

    Avoids a hard pyyaml dependency in this path and tolerates the folded
    ``description: >-`` block the skill uses.
    """
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    body = text[3:end]
    meta, key, folded = {}, "", []
    for line in body.splitlines():
        if not line.strip():
            continue
        if line[:1] not in (" ", "\t") and ":" in line:
            if key and folded:
                meta[key] = " ".join(folded).strip()
                folded = []
            k, _, v = line.partition(":")
            key = k.strip()
            v = v.strip()
            if v in (">-", ">", "|", "|-"):
                meta[key] = ""
            else:
                meta[key] = v.strip("'\"")
                key = ""
        elif key:
            folded.append(line.strip())
    if key and folded:
        meta[key] = " ".join(folded).strip()
    return meta


def read_skill_meta(skill_dir) -> dict:
    """{name, version, description} for a skill directory."""
    md = Path(skill_dir) / "SKILL.md"
    if not md.is_file():
        raise SkillInstallError(f"SKILL.md not found in {skill_dir}")
    try:
        text = md.read_text(encoding="utf-8")
    except OSError as e:
        raise SkillInstallError(f"cannot read {md}: {e}") from e
    meta = _parse_frontmatter(text)
    if not meta.get("name"):
        raise SkillInstallError(
            f"{md} has no 'name' in its YAML frontmatter — the file is "
            "malformed or truncated")
    return {
        "name": meta.get("name", ""),
        "version": meta.get("version", ""),
        "description": meta.get("description", ""),
        "path": str(Path(skill_dir).resolve()),
    }


def verify_skill_dir(skill_dir) -> dict:
    """Self-check a skill directory: SKILL.md parses, references present."""
    skill_dir = Path(skill_dir)
    meta = read_skill_meta(skill_dir)
    files = sorted(p.relative_to(skill_dir).as_posix()
                   for p in skill_dir.rglob("*") if p.is_file())
    if "SKILL.md" not in files:  # pragma: no cover — read_skill_meta covers it
        raise SkillInstallError("SKILL.md missing after copy")
    meta["files"] = files
    return meta


# ── target detection ─────────────────────────────────────────────────────────

def detect_targets(cwd=None, home=None) -> list:
    """Ranked install candidates.

    Ranking (best first):
      1. the skills directory already exists
      2. the agent itself is installed (marker dir present) — we'd create
         ``skills/`` inside it
      3. everything else, in table order

    Rank 2 is what makes Codex work out of the box: a fresh Codex install
    has ``~/.codex/`` but no ``~/.codex/skills/`` yet, and a plain
    "does the directory exist" check would silently skip it in favour of
    some other agent's folder.
    """
    roots = {
        "cwd": Path(cwd) if cwd else Path.cwd(),
        "home": Path(home) if home else Path.home(),
    }
    seen, candidates = set(), []
    for base, rel, label, marker in TARGET_CONVENTIONS:
        root = roots[base]
        path = (root / rel).expanduser()
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(Candidate(path, label, marker=marker,
                                    marker_path=(root / marker).expanduser()
                                    if marker else None,
                                    scope=base))
    # stable sort: preserves table order inside each rank
    candidates.sort(key=lambda c: (not c.exists, not c.agent_present))
    return candidates


def viable_targets(cwd=None, home=None) -> list:
    """Candidates we would actually install into (existing dir or known agent)."""
    return [c for c in detect_targets(cwd=cwd, home=home)
            if c.exists or c.agent_present]


def _stdin_is_interactive() -> bool:
    """True only when a human can answer a prompt (never in CI / pipes)."""
    try:
        return bool(sys.stdin) and sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):  # closed / replaced streams
        return False


def choose_target(cwd=None, home=None, interactive=None,
                  stream=None) -> Tuple[Path, str]:
    """Pick an install directory. Returns ``(path, how)``.

    ``how`` is ``'only'`` (one viable target), ``'chosen'`` (the human
    picked from a menu) or ``'auto'`` (multiple targets, non-interactive —
    first one wins and we say so loudly rather than blocking a script).
    """
    out = stream or sys.stderr
    cands = viable_targets(cwd=cwd, home=home)
    if not cands:
        raise NoAgentDetected(_no_target_message(
            detect_targets(cwd=cwd, home=home)))
    if len(cands) == 1:
        return cands[0].path, "only"

    if interactive is None:
        interactive = _stdin_is_interactive()

    if not interactive:
        print(f"ℹ️  检测到 {len(cands)} 个可安装位置，非交互环境自动选择第一个："
              f"\n     {cands[0].path}  [{cands[0].agent}]", file=out)
        print("   其他候选：", file=out)
        for c in cands[1:]:
            print(f"     - {c.path}  [{c.agent}]", file=out)
        print("   指定其他位置：golive skill install --target <DIR>"
              "（golive skill install --list-targets 查看全部）", file=out)
        return cands[0].path, "auto"

    print(f"检测到 {len(cands)} 个可安装位置：", file=out)
    for i, c in enumerate(cands, 1):
        print(f"  [{i}] {c.describe()}", file=out)
    try:
        raw = input(f"选择安装位置 [1-{len(cands)}]，回车用 1：").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n⚠️  已取消，使用第一个位置。", file=out)
        return cands[0].path, "auto"
    if not raw:
        return cands[0].path, "chosen"
    try:
        idx = int(raw)
    except ValueError:
        raise SkillInstallError(
            f"'{raw}' 不是有效编号（应为 1-{len(cands)}）")
    if not 1 <= idx <= len(cands):
        raise SkillInstallError(f"编号超出范围：{idx}（应为 1-{len(cands)}）")
    return cands[idx - 1].path, "chosen"


def resolve_target(target: Optional[str] = None, cwd=None, home=None,
                   interactive: Optional[bool] = None) -> Path:
    """Explicit --target, else the best auto-detected location."""
    if target:
        return Path(target).expanduser()
    return choose_target(cwd=cwd, home=home, interactive=interactive)[0]


def _no_target_message(candidates) -> str:
    """Phrased as guidance, not an error — no agent is a valid state."""
    lines = ["未检测到 AI agent（需要时运行 golive skill install，"
             "或用 --target <DIR> 指定目录）",
             "", "常见安装位置（创建后重新运行即可）："]
    lines += [f"  {c.path}" for c in candidates[:6]]
    return "\n".join(lines)


# ── install ──────────────────────────────────────────────────────────────────

def _copy_tree(src: Path, dst: Path) -> list:
    """Copy the skill's own files (no caches, no stray binaries)."""
    copied = []
    for path in sorted(src.rglob("*")):
        if path.is_dir():
            continue
        if "__pycache__" in path.parts or path.name.startswith("."):
            continue
        if path.suffix.lower() not in _COPY_SUFFIXES:
            continue
        rel = path.relative_to(src)
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out)
        copied.append(rel.as_posix())
    return copied


def _backup(existing: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = existing.with_name(f"{existing.name}.bak-{stamp}")
    shutil.move(str(existing), str(backup))
    return backup


def install(target: Optional[str] = None, from_github: bool = False,
            force: bool = False, cwd=None, home=None,
            interactive: Optional[bool] = None) -> dict:
    """Install the skill. Returns a dict describing the outcome."""
    if from_github:
        source, origin = _fetch_from_github(), "github"
    else:
        source, origin = packaged_skill_dir(), "package"
    if not (source / "SKILL.md").is_file():
        raise SkillInstallError(
            f"bundled skill is incomplete: {source / 'SKILL.md'} not found. "
            "Reinstall html-golive, or use --target with a manual copy of "
            "the skill directory.")

    meta = read_skill_meta(source)
    if target:
        target_dir, how = Path(target).expanduser(), "explicit"
    else:
        target_dir, how = choose_target(cwd=cwd, home=home,
                                        interactive=interactive)
    dest = target_dir / SKILL_NAME

    backup = None
    if dest.exists():
        if not force:
            raise SkillInstallError(
                f"{dest} already exists — re-run with --force to replace it "
                "(the current copy is backed up first)")
        backup = _backup(dest)

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        dest.mkdir(parents=True, exist_ok=True)
        copied = _copy_tree(source, dest)
        verified = verify_skill_dir(dest)
    except OSError as e:
        raise SkillInstallError(f"install failed: {e}") from e

    return {
        "installed_to": str(dest),
        "target_dir": str(target_dir),
        "target_choice": how,
        "origin": origin,
        "source": str(source),
        "files": copied,
        "backup": str(backup) if backup else "",
        "name": verified["name"],
        "version": verified["version"] or meta.get("version", ""),
    }


def _fetch_from_github() -> Path:
    """Download the skill from GitHub into a temp dir. Raises on failure."""
    import io
    import tarfile

    try:
        import requests
    except ImportError as e:  # pragma: no cover — requests is a hard dep
        raise SkillInstallError(
            "requests is required for --from-github "
            "(pip install requests), or drop the flag to install the "
            "version bundled with this package") from e

    try:
        resp = requests.get(GITHUB_TARBALL, timeout=30)
        resp.raise_for_status()
    except Exception as e:  # noqa: BLE001 — network/DNS/HTTP all land here
        raise SkillInstallError(
            f"could not download the skill from GitHub: {e}\n"
            "  Check network access, or drop --from-github to install the "
            "version bundled with this package (already on disk).") from e

    tmp = Path(tempfile.mkdtemp(prefix="golive-skill-"))
    try:
        with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tf:
            members = [m for m in tf.getmembers()
                       if "/golive/resources/skill/" in m.name and m.isfile()]
            if not members:
                raise SkillInstallError(
                    "the downloaded archive contains no skill directory — "
                    "the repository layout may have changed; drop "
                    "--from-github to use the bundled copy")
            for m in members:
                # flatten <repo>-main/golive/resources/skill/<rel>
                rel = m.name.split("/golive/resources/skill/", 1)[1]
                if not rel or rel.startswith("/") or ".." in rel:
                    continue
                out = tmp / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                src = tf.extractfile(m)
                if src is None:
                    continue
                out.write_bytes(src.read())
    except tarfile.TarError as e:
        raise SkillInstallError(f"downloaded archive is not readable: {e}") from e
    return tmp


# ── status / path ────────────────────────────────────────────────────────────

def find_installed(cwd=None, home=None) -> list:
    """Every detected location that already has the skill installed."""
    out = []
    for cand in detect_targets(cwd=cwd, home=home):
        dest = cand.path / SKILL_NAME
        if (dest / "SKILL.md").is_file():
            try:
                meta = read_skill_meta(dest)
            except SkillInstallError as e:
                out.append({"path": str(dest), "version": "",
                            "agent": cand.agent, "scope": cand.scope,
                            "error": str(e)})
                continue
            out.append({"path": str(dest),
                        "version": meta.get("version", ""),
                        "agent": cand.agent,
                        "scope": cand.scope,
                        "error": ""})
    return out


def status(cwd=None, home=None) -> dict:
    """Installed skill versions vs the version shipped with this golive."""
    from golive import __version__

    packaged = packaged_skill_dir()
    try:
        packaged_meta = read_skill_meta(packaged)
    except SkillInstallError as e:
        packaged_meta = {"version": "", "error": str(e)}

    installs = find_installed(cwd=cwd, home=home)
    current = packaged_meta.get("version", "")
    stale = [i for i in installs if i["version"] != current]
    return {
        "golive_version": __version__,
        "packaged_skill_version": current,
        "packaged_skill_path": str(packaged),
        "installs": installs,
        "install_count": len(installs),
        "stale": stale,
        "in_sync": bool(installs) and not stale,
        "candidates": [c.as_dict()
                       for c in detect_targets(cwd=cwd, home=home)],
    }
