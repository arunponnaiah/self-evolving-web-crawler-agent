from crawler_agent.discovery.authentic_domains import is_authentic_domain


def test_accepts_real_government_domains():
    assert is_authentic_domain("US", "https://www.federalregister.gov/documents/search")
    assert is_authentic_domain("GB", "https://www.legislation.gov.uk/uksi")
    assert is_authentic_domain("EU", "https://eur-lex.europa.eu/oj/direct-access.html")


def test_rejects_lookalike_domains():
    # Not under the real .gov TLD at all -- "gov" is just a word in the label.
    assert not is_authentic_domain("US", "https://irs-gov-refunds.com/claim")
    # Real TLD is .com; "gov.uk" is stuffed earlier in the string to deceive.
    assert not is_authentic_domain("GB", "https://legislation.gov.uk.evil.com/uksi")
    assert not is_authentic_domain("EU", "https://eur-lex.europa.eu.evil.com/oj")


def test_accepts_any_subdomain_of_an_authentic_tld():
    """Any subdomain under a government-controlled TLD (.gov, .gov.uk,
    .europa.eu) is itself authentic -- only that TLD's owner can register
    under it, so a never-seen subdomain name is not a lookalike risk."""
    assert is_authentic_domain("GB", "https://some-new-agency.gov.uk/register")
    assert is_authentic_domain("US", "https://some-new-agency.gov/register")


def test_rejects_unknown_country():
    assert not is_authentic_domain("ZZ", "https://example.gov/anything")


def test_rejects_url_with_no_domain():
    assert not is_authentic_domain("US", "not-a-url")
