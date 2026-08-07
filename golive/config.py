"""golive.config — golive.yaml loader with env-first overrides.

Lookup order (first hit wins):
  1. --config <path>           (CLI, passed via load_config(cli_path=...))
  2. $GOLIVE_CONFIG            (env)
  3. ./golive.yaml             (cwd)
  4. $GOLIVE_HOME/golive.yaml  (data dir)

No file found -> full defaults (the zero-config path stays untouched).

Env always wins over yaml (12-factor):
  GOLIVE_TOKEN                 -> auth.token (and implies provider=token)
  GOLIVE_UPLOADER_CMD          -> uploader.command
  GOLIVE_FONT_CDN_BASE         -> style.font_cdn_base
  GOLIVE_SUPABASE_URL          -> supabase.url (shared by all three layers)
  GOLIVE_SUPABASE_ANON_KEY     -> supabase anon key value
  GOLIVE_SUPABASE_SERVICE_KEY  -> supabase service_role key value
  GOLIVE_S3_ENDPOINT / GOLIVE_S3_BUCKET / GOLIVE_S3_AK / GOLIVE_S3_SK
                               -> storage.s3 / uploader.s3 defaults

Key material never lives in golive.yaml directly: yaml stores *_env names
(e.g. ``anon_key_env: GOLIVE_SUPABASE_ANON_KEY``) and the value is read
from the environment at runtime.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from golive.i18n import t as _t


class ConfigError(RuntimeError):
    """Raised when a config file exists but cannot be parsed."""


# ─────────────────────────── section dataclasses ────────────────────────────

@dataclass
class SupabaseConfig:
    """Shared Supabase connection block (top-level ``supabase:``)."""
    url: str = ""
    anon_key_env: str = "GOLIVE_SUPABASE_ANON_KEY"
    service_key_env: str = "GOLIVE_SUPABASE_SERVICE_KEY"

    @property
    def anon_key(self) -> str:
        return os.environ.get("GOLIVE_SUPABASE_ANON_KEY", "") \
            or os.environ.get(self.anon_key_env, "")

    @property
    def service_key(self) -> str:
        return os.environ.get("GOLIVE_SUPABASE_SERVICE_KEY", "") \
            or os.environ.get(self.service_key_env, "")

    @property
    def key(self) -> str:
        """Best key available for server-side calls (service_role > anon)."""
        return self.service_key or self.anon_key

    @property
    def configured(self) -> bool:
        return bool(self.url and self.key)


@dataclass
class StorageConfig:
    backend: str = "local"           # local | s3 | supabase
    # s3 sub-options
    s3_endpoint: str = ""
    s3_bucket: str = "golive-sites"
    s3_prefix: str = ""
    s3_region: str = ""
    s3_access_key_env: str = "GOLIVE_S3_AK"
    s3_secret_key_env: str = "GOLIVE_S3_SK"
    s3_public_base: str = ""         # optional CDN/public URL prefix
    # supabase sub-options
    supabase_bucket: str = "golive-sites"


@dataclass
class RegistryConfig:
    backend: str = "sqlite"          # sqlite | postgres | supabase
    postgres_dsn_env: str = "GOLIVE_PG_DSN"
    supabase_table: str = "golive_sites"


@dataclass
class DataConfig:
    """Data layer for published pages (window.TemplateAPI).

    backend:
      sqlite   — default; rows live in ``$GOLIVE_HOME/data.db`` and pages
                 reach them through ``golive serve``'s /api/data endpoint.
                 Zero configuration, no external service.
      supabase — rows live in your Supabase project; pages call PostgREST
                 directly with the anon key (configure RLS).
      none     — data layer disabled; TemplateAPI is injected as a stub
                 that errors with a configuration hint.
    """
    backend: str = "sqlite"          # sqlite | supabase | none
    templates_table: str = "golive_templates"
    user_id: str = ""                # identity stamped on rows ('' = anonymous)
    sqlite_path: str = ""            # override the data.db location
    api_base: str = ""               # public base URL of /api/data for pages


@dataclass
class AuthConfig:
    provider: str = "none"           # none | token | oidc | proxy
    token: str = ""
    # OIDC (M3 → v0.8.0) — generic OpenID Connect (Google / GitHub via OIDC
    # bridge / Keycloak / Authentik / any self-hosted IdP with a discovery
    # document). v0.8.0 adds id_token signature verification (RS256 via
    # JWKS), nonce, and full claims validation.
    oidc_issuer: str = ""            # https://idp.example.com (discovery base)
    oidc_client_id: str = ""
    oidc_client_secret_env: str = "GOLIVE_OIDC_CLIENT_SECRET"
    oidc_redirect_uri: str = ""      # e.g. http://localhost:8787/auth/callback
    oidc_scopes: str = "openid email profile"
    oidc_session_ttl: int = 8 * 3600   # seconds
    oidc_cookie_secret_env: str = "GOLIVE_COOKIE_SECRET"
    oidc_force_secure_cookie: bool = False
    oidc_verify_signature: bool = True  # v0.8.0 — default: verify id_token sig
    # Trusted reverse-proxy auth (v0.8.0)
    proxy_header: str = "X-Forwarded-User"
    proxy_email_header: str = ""     # optional; falls back to header value
    proxy_groups_header: str = ""    # optional
    proxy_trusted_ips: list = field(default_factory=list)

    @property
    def oidc_client_secret(self) -> str:
        return os.environ.get(self.oidc_client_secret_env, "")

    @property
    def oidc_cookie_secret(self) -> str:
        return os.environ.get(self.oidc_cookie_secret_env, "")


@dataclass
class EditorConfig:
    """Online editor (M3). Disabled per-site until publish --enable-editor."""
    token: str = ""                  # editor token; falls back to auth.token


@dataclass
class WatermarkConfig:
    """Front-end canvas watermark (M3)."""
    enabled: bool = False
    text: str = ""                   # static watermark text (identity source 2)
    opacity: float = 0.15
    font_size: int = 14
    rotation: int = -30              # degrees
    color: str = "150,150,150"       # rgb triplet
    cdn_url: str = ""                # serve JS from your own CDN instead of inline
    report_webhook: str = ""         # optional POST {slug,user,ua,ts}


@dataclass
class LLMConfig:
    """OpenAI-compatible endpoint for AI security review (M3)."""
    base_url: str = ""               # e.g. https://api.openai.com/v1
    api_key_env: str = "GOLIVE_LLM_API_KEY"
    model: str = "gpt-4o-mini"
    timeout: int = 20                # seconds
    strict_mode: bool = False        # True: refuse publish when LLM unset

    @property
    def api_key(self) -> str:
        return os.environ.get("GOLIVE_LLM_API_KEY", "") \
            or os.environ.get(self.api_key_env, "")

    @property
    def configured(self) -> bool:
        return bool(self.base_url)


@dataclass
class UploaderConfig:
    command: str = ""
    s3_endpoint: str = ""
    s3_bucket: str = ""
    s3_prefix: str = "img/"
    s3_region: str = ""
    s3_access_key_env: str = "GOLIVE_S3_AK"
    s3_secret_key_env: str = "GOLIVE_S3_SK"
    s3_public_base: str = ""


@dataclass
class StyleConfig:
    font_cdn_base: str = ""


@dataclass
class SecurityConfig:
    extra_rules: list = field(default_factory=list)
    llm: LLMConfig = field(default_factory=LLMConfig)


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8787
    public_base: str = ""            # printed in publish URLs when set


@dataclass
class AdminConfig:
    """Admin portal (M5). ``admins`` lists superadmin emails.

    env ``GOLIVE_ADMINS`` (comma separated) always wins over yaml —
    see golive.server.authz.get_admin_emails().

    ``audit_max_bytes`` / ``audit_keep`` control audit.log size rotation
    (M6): when the log exceeds ``audit_max_bytes`` it is renamed to
    ``audit.log.1`` (older archives shift up, ``audit_keep`` kept).
    0 disables rotation. env: GOLIVE_AUDIT_MAX_BYTES / GOLIVE_AUDIT_KEEP.
    """
    admins: list = field(default_factory=list)
    audit_max_bytes: int = 10 * 1024 * 1024   # 10 MB; 0 = no rotation
    audit_keep: int = 5                       # archived generations kept


@dataclass
class Config:
    storage: StorageConfig = field(default_factory=StorageConfig)
    registry: RegistryConfig = field(default_factory=RegistryConfig)
    data: DataConfig = field(default_factory=DataConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    uploader: UploaderConfig = field(default_factory=UploaderConfig)
    editor: EditorConfig = field(default_factory=EditorConfig)
    watermark: WatermarkConfig = field(default_factory=WatermarkConfig)
    style: StyleConfig = field(default_factory=StyleConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    admin: AdminConfig = field(default_factory=AdminConfig)
    supabase: SupabaseConfig = field(default_factory=SupabaseConfig)
    slug_reserved: list = field(default_factory=list)
    localize_never: list = field(default_factory=list)
    source_path: str = ""            # which yaml file was loaded ('' = defaults)


# ─────────────────────────────── file lookup ─────────────────────────────────

def _find_config_file(cli_path: Optional[str] = None) -> Optional[Path]:
    if cli_path:
        p = Path(cli_path).expanduser()
        if not p.exists():
            raise ConfigError(f"config file not found: {p}")
        return p
    env_path = os.environ.get("GOLIVE_CONFIG", "").strip()
    if env_path:
        p = Path(env_path).expanduser()
        if not p.exists():
            raise ConfigError(f"$GOLIVE_CONFIG points to a missing file: {p}")
        return p
    cwd_candidate = Path.cwd() / "golive.yaml"
    if cwd_candidate.exists():
        return cwd_candidate
    # avoid importing paths.get_home() (it mkdir's); resolve manually
    home_env = os.environ.get("GOLIVE_HOME", "").strip()
    home = Path(home_env).expanduser() if home_env else Path.home() / ".golive"
    home_candidate = home / "golive.yaml"
    if home_candidate.exists():
        return home_candidate
    return None


def _parse_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError as e:  # pragma: no cover
        raise ConfigError("pyyaml is required to read golive.yaml "
                          "(pip install pyyaml)") from e
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(
            f"invalid YAML in {path}:\n  {e}\n"
            f"  Fix the syntax or remove the file to fall back to defaults."
        ) from e
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at top level")
    return raw


# ─────────────────────────────── assembly ────────────────────────────────────

def _get(d: dict, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _build(raw: dict, source_path: str) -> Config:
    cfg = Config(source_path=source_path)

    # shared supabase block
    cfg.supabase.url = str(_get(raw, "supabase", "url", default="") or "")
    cfg.supabase.anon_key_env = str(_get(raw, "supabase", "anon_key_env",
                                         default=cfg.supabase.anon_key_env))
    cfg.supabase.service_key_env = str(_get(raw, "supabase", "service_key_env",
                                            default=cfg.supabase.service_key_env))

    # storage
    st = cfg.storage
    st.backend = str(_get(raw, "storage", "backend", default="local") or "local").lower()
    st.s3_endpoint = str(_get(raw, "storage", "s3", "endpoint", default="") or "")
    st.s3_bucket = str(_get(raw, "storage", "s3", "bucket", default=st.s3_bucket))
    st.s3_prefix = str(_get(raw, "storage", "s3", "prefix", default=""))
    st.s3_region = str(_get(raw, "storage", "s3", "region", default=""))
    st.s3_access_key_env = str(_get(raw, "storage", "s3", "access_key_env",
                                    default=st.s3_access_key_env))
    st.s3_secret_key_env = str(_get(raw, "storage", "s3", "secret_key_env",
                                    default=st.s3_secret_key_env))
    st.s3_public_base = str(_get(raw, "storage", "s3", "public_base", default=""))
    st.supabase_bucket = str(_get(raw, "storage", "supabase", "bucket",
                                  default=st.supabase_bucket))

    # registry
    rg = cfg.registry
    rg.backend = str(_get(raw, "registry", "backend", default="sqlite") or "sqlite").lower()
    rg.postgres_dsn_env = str(_get(raw, "registry", "postgres", "dsn_env",
                                   default=rg.postgres_dsn_env))
    rg.supabase_table = str(_get(raw, "registry", "supabase", "table",
                                 default=rg.supabase_table))

    # data layer
    dt = cfg.data
    dt.backend = str(_get(raw, "data", "backend", default="sqlite") or "sqlite").lower()
    dt.templates_table = str(_get(raw, "data", "supabase", "templates_table",
                                  default=dt.templates_table))
    dt.user_id = str(_get(raw, "data", "supabase", "user_id", default=""))
    dt.sqlite_path = str(_get(raw, "data", "sqlite", "path", default="") or "")
    dt.api_base = str(_get(raw, "data", "api_base", default="") or "").rstrip("/")

    # auth
    cfg.auth.provider = str(_get(raw, "auth", "provider", default="none") or "none").lower()
    cfg.auth.token = str(_get(raw, "auth", "token", default="") or "")
    au = cfg.auth
    # OIDC preset: fills public fields (issuer template, scopes) for a
    # named IdP; explicit auth.oidc.* below always override the preset.
    _preset_name = str(_get(raw, "auth", "oidc", "preset", default="") or "").strip()
    _preset: dict = {}
    if _preset_name:
        from golive.backends.auth.presets import resolve_preset
        try:
            _preset = resolve_preset(
                _preset_name,
                domain=str(_get(raw, "auth", "oidc", "domain", default="") or ""),
                tenant=str(_get(raw, "auth", "oidc", "tenant", default="") or ""),
                realm=str(_get(raw, "auth", "oidc", "realm", default="") or ""),
            )
        except ValueError as e:
            raise ConfigError(str(e))
    au.oidc_issuer = str(
        _get(raw, "auth", "oidc", "issuer", default="")
        or _preset.get("issuer", "")
    ).rstrip("/")
    au.oidc_client_id = str(_get(raw, "auth", "oidc", "client_id", default="") or "")
    au.oidc_client_secret_env = str(_get(raw, "auth", "oidc", "client_secret_env",
                                         default=au.oidc_client_secret_env))
    au.oidc_redirect_uri = str(_get(raw, "auth", "oidc", "redirect_uri", default="") or "")
    au.oidc_scopes = str(_get(raw, "auth", "oidc", "scopes",
                              default=_preset.get("scopes", "") or au.oidc_scopes)
                         or _preset.get("scopes", "") or au.oidc_scopes)
    try:
        au.oidc_session_ttl = int(_get(raw, "auth", "oidc", "session_ttl",
                                       default=au.oidc_session_ttl))
    except (TypeError, ValueError):
        raise ConfigError("auth.oidc.session_ttl must be an integer (seconds)")
    au.oidc_cookie_secret_env = str(_get(raw, "auth", "oidc", "cookie_secret_env",
                                         default=au.oidc_cookie_secret_env))
    au.oidc_force_secure_cookie = bool(_get(raw, "auth", "oidc",
                                            "force_secure_cookie", default=False))
    # v0.8.0: id_token signature verification (default: True)
    _verify_sig = _get(raw, "auth", "oidc", "verify_signature", default=True)
    # Handle explicit None/null → True (safe default)
    au.oidc_verify_signature = True if _verify_sig is None else bool(_verify_sig)

    # Trusted reverse-proxy auth (v0.8.0)
    _proxy = _get(raw, "auth", "proxy", default={}) or {}
    au.proxy_header = str(_proxy.get("header", au.proxy_header) or au.proxy_header)
    au.proxy_email_header = str(_proxy.get("email_header", "") or "")
    au.proxy_groups_header = str(_proxy.get("groups_header", "") or "")
    _trusted = _proxy.get("trusted_ips", [])
    au.proxy_trusted_ips = [str(ip).strip() for ip in _trusted
                            if str(ip).strip()] if isinstance(_trusted, (list, tuple)) else []

    # editor (M3)
    cfg.editor.token = str(_get(raw, "editor", "token", default="") or "")

    # watermark (M3)
    wm = cfg.watermark
    wm.enabled = bool(_get(raw, "watermark", "enabled", default=False))
    wm.text = str(_get(raw, "watermark", "text", default="") or "")
    try:
        wm.opacity = float(_get(raw, "watermark", "opacity", default=wm.opacity))
        wm.font_size = int(_get(raw, "watermark", "font_size", default=wm.font_size))
        wm.rotation = int(_get(raw, "watermark", "rotation", default=wm.rotation))
    except (TypeError, ValueError):
        raise ConfigError("watermark.opacity/font_size/rotation must be numeric")
    wm.color = str(_get(raw, "watermark", "color", default=wm.color) or wm.color)
    wm.cdn_url = str(_get(raw, "watermark", "cdn_url", default="") or "")
    wm.report_webhook = str(_get(raw, "watermark", "report_webhook", default="") or "")

    # uploader
    up = cfg.uploader
    up.command = str(_get(raw, "uploader", "command", default="") or "")
    up.s3_endpoint = str(_get(raw, "uploader", "s3", "endpoint", default=""))
    up.s3_bucket = str(_get(raw, "uploader", "s3", "bucket", default=""))
    up.s3_prefix = str(_get(raw, "uploader", "s3", "prefix", default=up.s3_prefix))
    up.s3_region = str(_get(raw, "uploader", "s3", "region", default=""))
    up.s3_access_key_env = str(_get(raw, "uploader", "s3", "access_key_env",
                                    default=up.s3_access_key_env))
    up.s3_secret_key_env = str(_get(raw, "uploader", "s3", "secret_key_env",
                                    default=up.s3_secret_key_env))
    up.s3_public_base = str(_get(raw, "uploader", "s3", "public_base", default=""))

    # style / security / server
    cfg.style.font_cdn_base = str(_get(raw, "style", "font_cdn_base", default="") or "")
    extra = _get(raw, "security", "extra_rules", default=[])
    cfg.security.extra_rules = list(extra) if isinstance(extra, (list, tuple)) else []
    llm = cfg.security.llm
    llm.base_url = str(_get(raw, "security", "llm", "base_url", default="") or "").rstrip("/")
    llm.api_key_env = str(_get(raw, "security", "llm", "api_key_env",
                               default=llm.api_key_env))
    llm.model = str(_get(raw, "security", "llm", "model",
                         default=llm.model) or llm.model)
    try:
        llm.timeout = int(_get(raw, "security", "llm", "timeout", default=llm.timeout))
    except (TypeError, ValueError):
        raise ConfigError("security.llm.timeout must be an integer (seconds)")
    llm.strict_mode = bool(_get(raw, "security", "llm", "strict_mode", default=False))
    cfg.server.host = str(_get(raw, "server", "host", default="127.0.0.1"))
    try:
        cfg.server.port = int(_get(raw, "server", "port", default=8787))
    except (TypeError, ValueError):
        raise ConfigError(f"server.port must be an integer "
                          f"(got {_get(raw, 'server', 'port')!r})")
    cfg.server.public_base = str(_get(raw, "server", "public_base", default="") or "").rstrip("/")

    # admin portal (M5)
    admins = _get(raw, "admin", "admins", default=[])
    cfg.admin.admins = [str(a).strip().lower() for a in admins if str(a).strip()] \
        if isinstance(admins, (list, tuple)) else []
    # audit rotation (M6)
    try:
        cfg.admin.audit_max_bytes = int(
            _get(raw, "admin", "audit_max_bytes",
                 default=cfg.admin.audit_max_bytes))
    except (TypeError, ValueError):
        raise ConfigError("admin.audit_max_bytes must be an integer")
    try:
        cfg.admin.audit_keep = int(
            _get(raw, "admin", "audit_keep", default=cfg.admin.audit_keep))
    except (TypeError, ValueError):
        raise ConfigError("admin.audit_keep must be an integer")

    reserved = _get(raw, "slug", "reserved", default=[])
    cfg.slug_reserved = [str(s).lower() for s in reserved] \
        if isinstance(reserved, (list, tuple)) else []
    never = _get(raw, "localize", "never", default=[])
    cfg.localize_never = list(never) if isinstance(never, (list, tuple)) else []

    return cfg


def _apply_env_overrides(cfg: Config) -> Config:
    tok = os.environ.get("GOLIVE_TOKEN", "").strip()
    if tok:
        cfg.auth.token = tok
        cfg.auth.provider = "token"
    up_cmd = os.environ.get("GOLIVE_UPLOADER_CMD", "").strip()
    if up_cmd:
        cfg.uploader.command = up_cmd
    font = os.environ.get("GOLIVE_FONT_CDN_BASE", "").strip()
    if font:
        cfg.style.font_cdn_base = font
    sb_url = os.environ.get("GOLIVE_SUPABASE_URL", "").strip()
    if sb_url:
        cfg.supabase.url = sb_url
    s3_ep = os.environ.get("GOLIVE_S3_ENDPOINT", "").strip()
    if s3_ep:
        cfg.storage.s3_endpoint = cfg.storage.s3_endpoint or s3_ep
        cfg.uploader.s3_endpoint = cfg.uploader.s3_endpoint or s3_ep
    s3_bucket = os.environ.get("GOLIVE_S3_BUCKET", "").strip()
    if s3_bucket:
        cfg.storage.s3_bucket = s3_bucket
    editor_tok = os.environ.get("GOLIVE_EDITOR_TOKEN", "").strip()
    if editor_tok:
        cfg.editor.token = editor_tok
    wm_text = os.environ.get("GOLIVE_WATERMARK_TEXT", "").strip()
    if wm_text:
        cfg.watermark.text = wm_text
    if os.environ.get("GOLIVE_WATERMARK_OFF", "").strip() == "1":
        cfg.watermark.enabled = False
    llm_base = os.environ.get("GOLIVE_LLM_BASE_URL", "").strip()
    if llm_base:
        cfg.security.llm.base_url = llm_base.rstrip("/")
    llm_model = os.environ.get("GOLIVE_LLM_MODEL", "").strip()
    if llm_model:
        cfg.security.llm.model = llm_model
    admins_env = os.environ.get("GOLIVE_ADMINS", "").strip()
    if admins_env:
        cfg.admin.admins = [a.strip().lower() for a in admins_env.split(",")
                            if a.strip()]
    for env_name, attr in (("GOLIVE_AUDIT_MAX_BYTES", "audit_max_bytes"),
                           ("GOLIVE_AUDIT_KEEP", "audit_keep")):
        v = os.environ.get(env_name, "").strip()
        if v:
            try:
                setattr(cfg.admin, attr, int(v))
            except ValueError:
                pass  # ignore malformed env — keep yaml/default
    return cfg


# ─────────────────────────────── public API ──────────────────────────────────

_current: Optional[Config] = None


KNOWN_SECTIONS = (
    "admin", "auth", "data", "editor", "localize", "registry", "security",
    "server", "slug", "storage", "style", "supabase", "uploader", "watermark",
)

# Settings people reasonably expect at the top level, but which actually
# live inside a section. Silently ignoring these is how someone ends up
# staring at "I listed myself as an admin and still have no access".
MISPLACED_HINTS = {
    "admins": "admin.admins",
    "token": "auth.token",
    "provider": "auth.provider",
    "oidc": "auth.oidc",
    "port": "server.port",
    "host": "server.host",
    "backend": "data.backend or storage.backend",
    "watermark_text": "watermark.text",
}


def check_unknown_sections(raw: dict) -> list:
    """Report top-level keys golive will ignore, with a fix where obvious.

    Returns a list of human-readable warnings; never raises. Unknown keys
    are not fatal — a config may legitimately carry comments or anchors
    for other tooling — but they should never be swallowed in silence.
    """
    if not isinstance(raw, dict):
        return []
    warnings = []
    for key in raw:
        name = str(key)
        if name in KNOWN_SECTIONS or name.startswith("x-") or name.startswith("_"):
            continue
        target = MISPLACED_HINTS.get(name)
        if target:
            warnings.append(
                "'{}' at the top level is ignored — move it to '{}'".format(name, target)
            )
        else:
            warnings.append("unknown top-level key '{}' is ignored".format(name))
    return warnings


def load_config(cli_path: Optional[str] = None) -> Config:
    """Load config fresh (no cache). Raises ConfigError on broken files."""
    path = _find_config_file(cli_path)
    raw = _parse_yaml(path) if path else {}
    for warning in check_unknown_sections(raw):
        print("⚠️  {}: {}".format(path or "golive.yaml", warning), file=sys.stderr)
    cfg = _build(raw, str(path) if path else "")
    return _apply_env_overrides(cfg)


def set_config(cfg: Config) -> None:
    """Install a Config as the process-wide current config (CLI entry).

    Also bridges yaml values into the legacy env read-points (only when
    the env var is not already set), so pre-config modules pick up
    golive.yaml without refactoring: GOLIVE_TOKEN / GOLIVE_UPLOADER_CMD /
    GOLIVE_FONT_CDN_BASE.
    """
    global _current
    _current = cfg
    if cfg.auth.token and not os.environ.get("GOLIVE_TOKEN"):
        os.environ["GOLIVE_TOKEN"] = cfg.auth.token
    if cfg.uploader.command and not os.environ.get("GOLIVE_UPLOADER_CMD"):
        os.environ["GOLIVE_UPLOADER_CMD"] = cfg.uploader.command
    if cfg.style.font_cdn_base and not os.environ.get("GOLIVE_FONT_CDN_BASE"):
        os.environ["GOLIVE_FONT_CDN_BASE"] = cfg.style.font_cdn_base


def get_config() -> Config:
    """Current config; lazily loads defaults if the CLI didn't set one."""
    global _current
    if _current is None:
        try:
            _current = load_config()
        except ConfigError as e:
            print(_t("config.parse_failed", error=e), file=sys.stderr)
            _current = Config()
    return _current


def reset_config() -> None:
    """Testing helper: forget the cached config."""
    global _current
    _current = None
