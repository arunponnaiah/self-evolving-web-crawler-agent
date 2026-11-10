from __future__ import annotations

from urllib.parse import urlparse

# Known legitimate government/regulatory domain suffixes per country. A
# candidate domain that doesn't match its country's list here is never
# fetched, never probed, and never registered -- this is a hard allowlist,
# not a heuristic, and it's the only thing standing between "ask an LLM for
# a URL" and actually visiting whatever it suggests. Extend this table to
# add more countries; do not loosen it to a fuzzy/substring match.
AUTHENTIC_DOMAIN_SUFFIXES: dict[str, list[str]] = {
    "US": [".gov"],
    "GB": [".gov.uk", "legislation.gov.uk", "parliament.uk"],
    "EU": [".europa.eu"],
    "CA": [".gc.ca", "canada.ca"],
    "AU": [".gov.au"],
    "DE": [".bund.de"],
    "FR": [".gouv.fr"],
}


def is_authentic_domain(country: str, url: str) -> bool:
    """True if `url`'s domain matches a known-legitimate suffix for `country`.

    Matching is by domain suffix only (e.g. "www.federalregister.gov" ends
    with ".gov") -- never by substring-anywhere-in-the-url, which would let
    a lookalike like "irs-gov-refunds.com" slip through.
    """
    suffixes = AUTHENTIC_DOMAIN_SUFFIXES.get(country.upper())
    if not suffixes:
        return False
    domain = urlparse(url).netloc.lower()
    if not domain:
        return False
    normalized = [s.lstrip(".") for s in suffixes]
    # Exact match, or match with a dot boundary -- "legislation.gov.uk"
    # matches "www.legislation.gov.uk" but not "xlegislation.gov.uk".
    return any(domain == s or domain.endswith(f".{s}") for s in normalized)
