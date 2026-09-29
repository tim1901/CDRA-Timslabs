from urllib.parse import urlparse
import re


def normalize_company(value: str) -> tuple[str, str | None]:
    value = value.strip()
    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlparse(value)
        domain = parsed.netloc.lower().removeprefix("www.")
        name = domain.split(".")[0].replace("-", " ").title()
        return name, domain
    if "linkedin.com/company/" in value:
        slug = value.rstrip("/").split("/company/")[-1].split("/")[0]
        return slug.replace("-", " ").title(), None
    if "." in value and " " not in value:
        domain = value.lower().removeprefix("www.")
        name = domain.split(".")[0].replace("-", " ").title()
        return name, domain
    return value, None


def domain_for_company(company: str, discovered_urls: list[str]) -> str | None:
    for url in discovered_urls:
        host = urlparse(url).netloc.lower().removeprefix("www.")
        if host and host not in {"duckduckgo.com"}:
            return host
    return None
