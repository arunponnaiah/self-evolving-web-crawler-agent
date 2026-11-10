from pathlib import Path

from crawler_agent.layout.fingerprint import compute_fingerprint

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_same_layout_different_content_same_fingerprint():
    fp_a = compute_fingerprint(_load("layout_v1_a.html"))
    fp_b = compute_fingerprint(_load("layout_v1_b.html"))
    assert fp_a == fp_b


def test_different_layout_different_fingerprint():
    fp_v1 = compute_fingerprint(_load("layout_v1_a.html"))
    fp_v2 = compute_fingerprint(_load("layout_v2.html"))
    assert fp_v1 != fp_v2


def test_fingerprint_is_deterministic():
    html = _load("layout_v1_a.html")
    assert compute_fingerprint(html) == compute_fingerprint(html)
