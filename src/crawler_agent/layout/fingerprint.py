from __future__ import annotations

import hashlib
from collections import Counter

from bs4 import Tag

from crawler_agent.utils.html_clean import clean_soup


def _tag_paths(root: Tag) -> Counter[str]:
    counter: Counter[str] = Counter()

    def walk(node: Tag, path: str) -> None:
        for child in node.find_all(True, recursive=False):
            classes = ".".join(sorted(child.get("class", [])))
            label = child.name + (f".{classes}" if classes else "")
            child_path = f"{path}>{label}"
            counter[child_path] += 1
            walk(child, child_path)

    walk(root, "root")
    return counter


def compute_fingerprint(html: str) -> str:
    """Structural signature of a page's DOM shape, ignoring text content.

    Two pages with the same tag/class skeleton hash identically even if the
    article text (or number of repeated list items) differs; a real layout
    change -- new wrapper elements, renamed classes, restructured sections --
    changes the hash. This is what lets the agent tell "same layout, new
    content" apart from "the site changed its page layout".
    """
    soup = clean_soup(html)
    paths = _tag_paths(soup)
    shape = sorted(paths.keys())
    return hashlib.sha256("\n".join(shape).encode("utf-8")).hexdigest()
