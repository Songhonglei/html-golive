"""Strong content revisions for conditional editor writes."""

import hashlib


def content_revision(html: str) -> str:
    return '"' + hashlib.sha256(html.encode("utf-8")).hexdigest() + '"'


class ContentConflict(Exception):
    def __init__(self, current_revision):
        self.current_revision = current_revision
        super().__init__("Content changed; reload and compare before retrying")
