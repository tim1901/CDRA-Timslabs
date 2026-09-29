from cdra.crawler.company import normalize_company

def test_domain():
    assert normalize_company("https://www.acme.com") == ("Acme", "acme.com")

def test_name():
    assert normalize_company("Acme Inc") == ("Acme Inc", None)
