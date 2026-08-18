"""Injected layers identify themselves; tools must not guess from the id.

Every injected ``<script>`` carries ``data-golive-layer`` /
``data-golive-schema`` / ``data-golive-version``, and
``golive.inject.LAYERS`` is the single list of what exists.

Two bugs motivated this:

* ``migrate-check`` kept its own literal list of element ids and looked for
  ``inline-editor-layer``, but the editor injects ``golive-inline-editor``.
  Editor leftovers were never reported — invisibly, because a regex that
  matches nothing looks exactly like a page with nothing to report.
* Every match was then labelled a leftover *data* layer, advising that
  "republishing swaps in the current data layer automatically". True for the
  data layers, wrong for watermark and editor: those are re-injected only
  when their own flag is passed, so a page could be called clean while
  silently keeping either one.
"""
from __future__ import annotations

import re
import unittest

from golive.core.migrate_check import scan_html
from golive.inject import (
    ATTR_LAYER,
    LAYERS,
    LEGACY_SCRIPT_IDS,
    all_script_ids,
    layer_attrs,
    layer_by_script_id,
)

BASE_HTML = ("<html><head><title>t</title></head>"
             "<body><p>hi</p></body></html>")


def _tag(script_id: str, kind: str = "") -> str:
    attrs = f' {ATTR_LAYER}="{kind}"' if kind else ""
    return (f'<html><body><script id="{script_id}"{attrs}>x</script>'
            f'</body></html>')


class TestEveryInjectorTagsItself(unittest.TestCase):
    """The real injectors, not hand-written script tags."""

    def _inject(self, kind: str) -> str:
        from golive.config import get_config
        from golive.inject import editor, supabase_api, template_api, watermark
        cfg = get_config()
        if kind == "data":
            return template_api.inject_into_html(BASE_HTML, "m1", cfg=cfg)
        if kind == "supabase":
            return supabase_api.inject_into_html(BASE_HTML, cfg=cfg)
        if kind == "watermark":
            return watermark.inject_into_html(BASE_HTML, text="X", cfg=cfg)
        return editor.inject_into_html(BASE_HTML, slug="s1", site_name="n")

    def test_each_layer_declares_kind_schema_and_version(self):
        for layer in LAYERS:
            with self.subTest(layer=layer.kind):
                html = self._inject(layer.kind)
                found = re.search(
                    r'data-golive-layer="(\w+)"[^>]*'
                    r'data-golive-schema="(\d+)"[^>]*'
                    r'data-golive-version="([\d.]+)"', html)
                self.assertIsNotNone(
                    found, f"{layer.kind} injected no identifying attributes")
                self.assertEqual(found.group(1), layer.kind)

    def test_injection_is_still_idempotent(self):
        """Adding attributes must not break the same-id replacement."""
        for layer in LAYERS:
            with self.subTest(layer=layer.kind):
                once = self._inject(layer.kind)
                # Re-inject over the already-injected page.
                from golive.config import get_config
                from golive.inject import (editor, supabase_api, template_api,
                                           watermark)
                cfg = get_config()
                if layer.kind == "data":
                    twice = template_api.inject_into_html(once, "m1", cfg=cfg)
                elif layer.kind == "supabase":
                    twice = supabase_api.inject_into_html(once, cfg=cfg)
                elif layer.kind == "watermark":
                    twice = watermark.inject_into_html(once, text="X", cfg=cfg)
                else:
                    twice = editor.inject_into_html(
                        once, slug="s1", site_name="n")
                self.assertEqual(
                    twice.count(f'id="{layer.script_id}"'), 1,
                    f"{layer.kind} was injected twice")


class TestDetectionCoversEveryLayer(unittest.TestCase):

    def test_no_layer_goes_undetected(self):
        """The editor was invisible to migrate-check before v0.8.2."""
        for layer in LAYERS:
            with self.subTest(layer=layer.kind):
                hits = scan_html(_tag(layer.script_id, layer.kind))["layer_hits"]
                self.assertTrue(
                    hits, f"{layer.script_id} was not detected at all")

    def test_the_editor_id_in_particular_is_detected(self):
        """Named explicitly: this is the id that drifted."""
        editor = layer_by_script_id("golive-inline-editor")
        self.assertIsNotNone(editor, "the editor left the layer list")
        hits = scan_html(_tag("golive-inline-editor"))["layer_hits"]
        self.assertTrue(hits)

    def test_legacy_layers_are_reported_as_legacy(self):
        for script_id in LEGACY_SCRIPT_IDS:
            with self.subTest(script_id=script_id):
                hits = scan_html(_tag(script_id))["layer_hits"]
                self.assertTrue(hits, f"{script_id} not detected")
                self.assertIn("older", hits[0]["label"].lower())

    def test_a_renamed_id_is_still_caught_via_the_attribute(self):
        """The whole point of the attribute: survive an id rename."""
        hits = scan_html(_tag("some-future-name", "editor"))["layer_hits"]
        self.assertTrue(
            hits, "a renamed layer became invisible again")

    def test_a_layer_is_not_counted_twice(self):
        hits = scan_html(_tag("watermark-layer", "watermark"))["layer_hits"]
        self.assertEqual(len(hits), 1)

    def test_a_page_with_no_layers_reports_nothing(self):
        clean = "<html><body><script>console.log(1)</script></body></html>"
        self.assertEqual(scan_html(clean)["layer_hits"], [])


class TestAdviceMatchesWhatTheLayerActuallyIs(unittest.TestCase):

    def _advice(self, layer) -> str:
        hits = scan_html(_tag(layer.script_id, layer.kind))["layer_hits"]
        return hits[0]["advice"]

    def test_data_layers_are_told_republishing_replaces_them(self):
        for layer in (item for item in LAYERS if item.is_data):
            with self.subTest(layer=layer.kind):
                self.assertIn("swaps", self._advice(layer))

    def test_non_data_layers_are_not_promised_an_automatic_swap(self):
        """Republishing does not re-inject these unless the flag is passed."""
        for layer in (item for item in LAYERS if not item.is_data):
            with self.subTest(layer=layer.kind):
                advice = self._advice(layer)
                self.assertIn("NOT replace", advice)
                self.assertIn(layer.label, advice)


class TestTheLayerListIsTheSingleSource(unittest.TestCase):

    def test_detection_ids_come_from_the_layer_list(self):
        ids = all_script_ids()
        for layer in LAYERS:
            self.assertIn(layer.script_id, ids)
        for legacy in LEGACY_SCRIPT_IDS:
            self.assertIn(legacy, ids)

    def test_migrate_check_does_not_hardcode_its_own_id_list(self):
        import inspect

        from golive.core import migrate_check
        src = inspect.getsource(migrate_check)
        # The ids must arrive from the inject package, not be spelled out here.
        self.assertIn("all_script_ids", src)
        for layer in LAYERS:
            self.assertNotIn(
                f'"{layer.script_id}"', src,
                f"{layer.script_id} is hardcoded in migrate_check; the list "
                f"will drift again")

    def test_layer_attrs_reports_the_running_version(self):
        from golive import __version__
        self.assertIn(__version__, layer_attrs("data"))


if __name__ == "__main__":
    unittest.main()
