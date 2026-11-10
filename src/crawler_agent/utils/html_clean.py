from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

STRIP_TAGS = ("script", "style", "nav", "footer", "header", "noscript", "svg", "form")

# Some sites' Atom/OpenSearch feeds (e.g. legislation.gov.uk) prepend a large
# facet/year-count block before the actual <entry> documents. It's pure
# navigation metadata, not content, but it's big enough to push every real
# entry past the max_chars truncation window if left in.
_FACETS_BLOCK_RE = re.compile(r"<leg:facets>.*?</leg:facets>", re.DOTALL)


def clean_soup(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(STRIP_TAGS):
        tag.decompose()
    return soup


def to_text(html: str, max_chars: int = 15_000, base_url: str | None = None) -> str:
    """Simplified text for the LLM prompt: boilerplate stripped, whitespace collapsed.

    Link hrefs are inlined next to their anchor text (resolved to absolute URLs
    when `base_url` is given) so the LLM can copy a document's real URL rather
    than guess/hallucinate one from plain visible text, which otherwise varies
    between identical crawls and silently produces duplicate/garbage records.
    """
    soup = clean_soup(html)
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]) if base_url else a["href"]
        a.append(f" ({href})")
    text = soup.get_text(separator="\n")
    text = _FACETS_BLOCK_RE.sub("", text)
    lines = [line.strip() for line in text.splitlines()]
    collapsed = "\n".join(line for line in lines if line)
    return collapsed[:max_chars]
