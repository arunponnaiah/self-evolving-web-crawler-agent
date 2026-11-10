from crawler_agent.fetch.browser_fetcher import select_markdown


def test_meaningful_pruning_is_used():
    """Mirrors the EUR-Lex daily-view page: pruning cut ~107KB of HTML-derived
    markdown down to a few KB of real content -- that result should be used."""
    raw = "chrome " * 10_000 + "real content"
    fit = "real content"
    assert select_markdown(raw, fit) == fit


def test_no_pruning_benefit_falls_back_to_none():
    """Mirrors the UK Atom feed rendered inside a single <pre> tag: there's no
    DOM structure to prune, so fit ~= raw and offers no benefit -- callers
    should fall back to the existing to_text() cleaning pipeline instead."""
    raw = "<feed>...entries...</feed>"
    fit = raw
    assert select_markdown(raw, fit) is None


def test_empty_markdown_falls_back_to_none():
    assert select_markdown("", "") is None
    assert select_markdown("some raw text", "") is None
