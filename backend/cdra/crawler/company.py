from urllib.parse import urlparse
import re


def _clean_domain(value: str) -> str:
    return value.lower().strip().removeprefix("www.").rstrip("/")


def _name_from_domain(domain: str) -> str:
    # Keep the registrable-name portion as the initial company identity.
    # The LLM/entity gate can refine ambiguous names later.
    label = domain.split(".")[0]
    return re.sub(r"[-_]+", " ", label).strip().title()


def normalize_company(value: str) -> tuple[str, str | None]:
    value = value.strip()
    if value.startswith(("http://", "https://")):
        parsed = urlparse(value)
        domain = _clean_domain(parsed.netloc)
        return _name_from_domain(domain), domain

    if "linkedin.com/company/" in value.lower():
        slug = value.rstrip("/").split("/company/")[-1].split("/")[0]
        return slug.replace("-", " ").title(), None

    if "." in value and " " not in value:
        domain = _clean_domain(value)
        return _name_from_domain(domain), domain

    return value, None


def domain_for_company(company: str, discovered_urls: list[str]) -> str | None:
    # Deprecated fallback. Never infer a company's canonical domain from an
    # arbitrary search result; the user's supplied URL should remain the
    # authoritative domain when available.
    for url in discovered_urls:
        host = urlparse(url).netloc.lower().removeprefix("www.")
        if host and host not in {"duckduckgo.com"}:
            return host
    return None
