"""golive.inject — JS layer injection.

Modules:
  template_api  window.TemplateAPI  (intranet-compatible signatures)
  supabase_api  window.SupabaseAPI  (intranet-compatible signatures)
  watermark     canvas identity watermark (M3)
  editor        online inline editor (M3)
  _escape       shared XSS-safe inlining helpers (single source of truth)

Each module exposes:
  generate_js(...)        -> full <script> tag string
  inject_into_html(...)   -> idempotent injection (replaces same-id script)

Script element ids (also used by migrate-check detection):
  template-data-layer / supabase-data-layer / watermark-layer /
  golive-inline-editor
"""

from __future__ import annotations

TEMPLATE_SCRIPT_ID = "template-data-layer"
SUPABASE_SCRIPT_ID = "supabase-data-layer"

# M3 registration slot: watermark / editor layers append here.
INJECTORS = {}


def register(name: str, module) -> None:
    INJECTORS[name] = module
