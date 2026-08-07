"""golive.i18n — minimal internationalisation for the CLI.

Language detection priority:
    1. ``GOLIVE_LANG`` environment variable
    2. System locale (``locale.getlocale()`` → ``LANG``/``LC_ALL`` env)
    3. English fallback

The default is **English**. Chinese is only selected when the environment
is unambiguously Chinese (``zh``, ``zh_CN``, ``zh-Hans``, etc.).

API:
    ``t(key, **kwargs)`` — look up *key* in the active language table,
    interpolate ``{name}`` placeholders, and fall back to English then to
    the key itself when a translation is missing.

Translation tables live in ``golive/locales/en.py`` and ``golive/locales/zh.py``
(pure Python dicts). No JSON, no gettext, no .po files — just dicts.
"""

from __future__ import annotations

import locale
import os
import re

__all__ = ["t", "get_language", "set_language"]

_cached_lang: str | None = None
_override: str | None = None


def _detect_lang() -> str:
    """Return ``"en"`` or ``"zh"`` based on environment + locale."""
    # 1. Explicit override via set_language()
    if _override:
        return _normalize(_override)

    # 2. GOLIVE_LANG env var
    env_val = os.environ.get("GOLIVE_LANG", "").strip()
    if env_val:
        return _normalize(env_val)

    # 3. System locale
    try:
        loc, _enc = locale.getlocale()
        if loc:
            return _normalize(loc)
    except (ValueError, TypeError):
        pass

    # 3b. LANG / LC_ALL environment variables
    for var in ("LC_ALL", "LANG"):
        val = os.environ.get(var, "").strip()
        if val and val != "C" and val != "POSIX":
            return _normalize(val)

    # 4. Fallback
    return "en"


def _normalize(raw: str) -> str:
    """Map a locale string to ``"en"`` or ``"zh"``; unknown → ``"en"``."""
    low = raw.lower().replace("-", "_").replace(" ", "")
    # Chinese variants: zh, zh_cn, zh_cn.utf8, zh_hans, zh_tw, zh_hk
    if low.startswith("zh"):
        return "zh"
    # English variants: en, en_us, en_gb, c.utf8 → en
    if low.startswith("en"):
        return "en"
    # Some systems use C or POSIX — treat as English
    if low in ("c", "posix", ""):
        return "en"
    # Unrecognised → English (don't guess)
    return "en"


def get_language() -> str:
    """Current language (``"en"`` or ``"zh"``)."""
    global _cached_lang
    if _cached_lang is None:
        _cached_lang = _detect_lang()
    return _cached_lang


def set_language(lang: str) -> None:
    """Override the language for this process (``"en"`` / ``"zh"``)."""
    global _override, _cached_lang
    _override = _normalize(lang)
    _cached_lang = _override


def _load_table(lang: str) -> dict:
    """Import the translation dict for *lang*."""
    if lang == "zh":
        from golive.locales import zh as mod
    else:
        from golive.locales import en as mod
    return mod.TRANSLATIONS


def t(key: str, **kwargs) -> str:
    """Look up *key*, interpolate ``{name}`` placeholders, fall back gracefully.

    Lookup chain: active language → English → return *key*.
    """
    lang = get_language()

    # Try active language first
    table = _load_table(lang)
    val = table.get(key)

    # Fall back to English
    if val is None and lang != "en":
        en_table = _load_table("en")
        val = en_table.get(key)

    # Fall back to the key itself
    if val is None:
        return key

    # Interpolate {name} placeholders
    if kwargs:
        try:
            return val.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return val
    return val
