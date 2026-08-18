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

Identifying an injected layer
-----------------------------
Every injected ``<script>`` carries explicit attributes:

    <script id="template-data-layer"
            data-golive-layer="data"
            data-golive-schema="2"
            data-golive-version="0.8.2">

``data-golive-layer`` says *what kind* of layer it is; the element id stays
for backwards compatibility and idempotent replacement.

Tools must read the attribute, not pattern-match the id. Recognising layers
by id meant every consumer kept its own list of id strings, and those lists
drifted: ``migrate-check`` looked for ``inline-editor-layer`` while the
editor actually injects ``golive-inline-editor``, so editor leftovers went
undetected — silently, since a regex that matches nothing looks the same as
a page with nothing to report. ``LAYERS`` below is the one list; add an entry
here when adding a layer, and consumers pick it up without changes.
"""

from __future__ import annotations

from typing import NamedTuple

TEMPLATE_SCRIPT_ID = "template-data-layer"
SUPABASE_SCRIPT_ID = "supabase-data-layer"
WATERMARK_SCRIPT_ID = "watermark-layer"
EDITOR_SCRIPT_ID = "golive-inline-editor"

#: Bumped when the injected contract changes shape, not on every release.
LAYER_SCHEMA = "2"

# Attribute names, kept here so a typo shows up in one place.
ATTR_LAYER = "data-golive-layer"
ATTR_SCHEMA = "data-golive-schema"
ATTR_VERSION = "data-golive-version"


class Layer(NamedTuple):
    """One injectable layer.

    kind         value of ``data-golive-layer``
    script_id    element id, kept stable for idempotent replacement
    is_data      whether republishing swaps this layer for the current
                 data backend — false for watermark and editor, which are
                 re-injected only when their own flags are set
    label        short human name for reports
    """

    kind: str
    script_id: str
    is_data: bool
    label: str


LAYERS = (
    Layer("data", TEMPLATE_SCRIPT_ID, True, "TemplateAPI data layer"),
    Layer("supabase", SUPABASE_SCRIPT_ID, True, "Supabase data layer"),
    Layer("watermark", WATERMARK_SCRIPT_ID, False, "watermark"),
    Layer("editor", EDITOR_SCRIPT_ID, False, "inline editor"),
)

#: Layers that older golive versions injected but current versions do not.
#: Still worth reporting as leftovers when found in a page.
LEGACY_SCRIPT_IDS = (
    "bi-data-layer",
    "api-proxy-layer",
    "access-data-layer",
)


def layer_attrs(kind: str) -> str:
    """Attribute string for a layer's ``<script>`` tag.

    Callers embed this directly, e.g.::

        f'<script id="{SCRIPT_ID}" {layer_attrs("data")}>'
    """
    from golive import __version__
    return (f'{ATTR_LAYER}="{kind}" '
            f'{ATTR_SCHEMA}="{LAYER_SCHEMA}" '
            f'{ATTR_VERSION}="{__version__}"')


def layer_by_script_id(script_id: str):
    """The :class:`Layer` with this element id, or ``None``."""
    for layer in LAYERS:
        if layer.script_id == script_id:
            return layer
    return None


def all_script_ids() -> tuple:
    """Every id worth looking for in a page: current layers plus legacy."""
    return tuple(item.script_id for item in LAYERS) + LEGACY_SCRIPT_IDS


# M3 registration slot: watermark / editor layers append here.
INJECTORS = {}


def register(name: str, module) -> None:
    INJECTORS[name] = module
