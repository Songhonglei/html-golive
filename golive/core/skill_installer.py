"""golive.core.skill_installer — install the bundled agent skill.

golive ships an AgentSkill (``golive/resources/skill/``) that teaches an
AI coding assistant how to drive the local ``golive`` CLI: probe the
environment first, publish/update/roll back, wire up the data layer, and
avoid confusing golive with any similarly named hosted service.

``golive skill install`` copies that directory into the agent's skills
folder. Targets are auto-detected from a table of common conventions
(project-local first, then user-level); nothing is hard-coded to a single
product, and unknown setups are handled by ``--target``.

Public API:
  packaged_skill_dir()      -> Path of the skill shipped inside the wheel
  read_skill_meta(dir)      -> {name, version, description} from frontmatter
  detect_targets()          -> [Candidate, ...] ranked, existing first
  install(...)              -> dict describing what happened
  status()                  -> installed-vs-current version comparison
"""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

SKILL_NAME = "html-golive"
GITHUB_REPO = "Songhonglei/html-golive"
GITHUB_TARBALL = f"https://github.com/{GITHUB_REPO}/archive/refs/heads/main.tar.gz"

#: Where agents keep skills. Ordered: project-local beats user-level, and
#: within each tier the more specific convention comes first. Extend this
#: table rather than adding conditionals elsewhere.
TARGET_CONVENTIONS = (
    # (relative-to, path template, label)
    ("cwd",  ".claude/skills",           "project skills directory"),
    ("cwd",  ".agent/skills",            "project skills directory"),
    ("cwd",  ".config/agent/skills",     "project skills directory"),
    ("cwd",  "skills",                   "project skills directory"),
    ("home", ".claude/skills",           "user skills directory"),
    ("home", ".agent/skills",            "user skills directory"),
    ("home", ".config/agent/skills",     "user skills directory"),
    ("home", ".local/share/agent/skills", "user skills directory"),
)

#: Files copied into the target (everything else is ignored).
_COPY_SUFFIXES = (".md", ".txt", ".json", ".yaml", ".yml", ".py", ".sh")


class SkillInstallError(RuntimeError):
    """Raised for anything the caller should see as a clean CLI error."""


class Candidate:
    """One possible install location."""

    __slots__ = ("path", "label", "exists")

    def __init__(self, path: Path, label: str):
        self.path = path
        self.label = label
        self.exists = path.is_dir()

    def __repr__(self):  # pragma: no cover — debugging aid
        return f"<Candidate {self.path} exists={self.exists}>"


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
    """Ranked install candidates: existing directories first."""
    roots = {
        "cwd": Path(cwd) if cwd else Path.cwd(),
        "home": Path(home) if home else Path.home(),
    }
    seen, candidates = set(), []
    for base, rel, label in TARGET_CONVENTIONS:
        path = (roots[base] / rel).expanduser()
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(Candidate(path, label))
    candidates.sort(key=lambda c: not c.exists)   # existing dirs first
    return candidates


def resolve_target(target: Optional[str] = None, cwd=None, home=None) -> Path:
    """Explicit --target, else the best auto-detected existing directory."""
    if target:
        return Path(target).expanduser()
    for cand in detect_targets(cwd=cwd, home=home):
        if cand.exists:
            return cand.path
    raise SkillInstallError(_no_target_message(detect_targets(cwd=cwd,
                                                              home=home)))


def _no_target_message(candidates) -> str:
    lines = ["could not detect a skills directory — pass --target <DIR>",
             "", "common locations (create one, then re-run):"]
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
            force: bool = False, cwd=None, home=None) -> dict:
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
    target_dir = resolve_target(target, cwd=cwd, home=home)
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
                            "error": str(e)})
                continue
            out.append({"path": str(dest),
                        "version": meta.get("version", ""),
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
        "stale": stale,
        "in_sync": bool(installs) and not stale,
    }
