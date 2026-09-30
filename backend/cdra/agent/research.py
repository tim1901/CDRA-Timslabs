from datetime import date
from dateutil.relativedelta import relativedelta
from urllib.parse import urlparse
import re
import httpx
from ..config import settings
from ..crawler.search import Searcher
from ..crawler.fetch import Fetcher, Page
from ..crawler.company import normalize_company
from .planner import build_queries
from .llm import LLM
from ..models.schemas import CompanyResult


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _entity_match(company: str, domain: str | None, url: str, title: str, snippet: str, text: str) -> bool:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    target_domain = domain.lower().removeprefix("www.") if domain else None
    if target_domain and (host == target_domain or host.endswith("." + target_domain)):
        return True
    fields = [_normalize_text(title), _normalize_text(snippet), _normalize_text(text[:20000])]
    if target_domain:
        domain_identity = _normalize_text(target_domain)
        if any(re.search(rf"(?<![a-z0-9]){re.escape(domain_identity)}(?![a-z0-9])", field) for field in fields):
            return True
    target = _normalize_text(company)
    if not target:
        return False
    if not target_domain or len(target.split()) > 1:
        if any(re.search(rf"(?<![a-z0-9]){re.escape(target)}(?![a-z0-9])", field) for field in fields):
            return True
    return False


def _dedupe(developments):
    kept = []
    for d in sorted(developments, key=lambda x: (x.confidence, x.date), reverse=True):
        duplicate = False
        for existing in kept:
            if d.type != existing.type:
                continue
            d_tokens = set(re.findall(r"[a-z0-9]+", d.title.lower()))
            e_tokens = set(re.findall(r"[a-z0-9]+", existing.title.lower()))
            similarity = __import__("difflib").SequenceMatcher(None, d.title.lower(), existing.title.lower()).ratio()
            overlap = len(d_tokens & e_tokens) / max(1, len(d_tokens | e_tokens))
            same_event = similarity >= 0.72 or overlap >= 0.55
            close_date = abs((date.fromisoformat(d.date) - date.fromisoformat(existing.date)).days) <= 14
            if same_event and close_date:
                duplicate = True
                break
        if not duplicate:
            kept.append(d)
    return sorted(kept, key=lambda x: x.date, reverse=True)


class ResearchAgent:
    def __init__(self):
        headers = {"User-Agent": settings.user_agent, "Accept-Language": "en-US,en;q=0.8"}
        self.client = httpx.Client(headers=headers, timeout=settings.request_timeout)
        self.searcher = Searcher(self.client, settings.max_sources_per_query)
        self.fetcher = Fetcher(self.client)
        self.llm = LLM(settings.openai_api_key, settings.openai_model)

    def run(self, company_input: str, lookback_months: int, types: list[str]) -> CompanyResult:
        company, domain = normalize_company(company_input)
        window_from = (date.today() - relativedelta(months=lookback_months)).isoformat()
        window_to = date.today().isoformat()
        warnings = []
        candidates = []
        seen = set()
        search_hits = 0
        fetch_failures = 0
        rejected_entities = 0
        llm_candidates = 0

        # Build a broad candidate pool from direct first-party discovery plus
        # complementary web/news search. Google News is now one discovery
        # channel rather than the critical path.
        if domain:
            for result in self.searcher.discover_first_party(domain, max_pages=16):
                canonical = result.url.split("#", 1)[0].rstrip("/")
                if canonical not in seen:
                    seen.add(canonical)
                    candidates.append(("first_party", result.url, result.published_date, result.title, result.snippet))
        first_party_count = len(candidates)

        queries = build_queries(company, lookback_months, types, domain=domain)
        for kind, query in queries:
            results = self.searcher.search(query)
            search_hits += len(results)
            for result in results:
                canonical = result.url.split("#", 1)[0].rstrip("/")
                if canonical in seen:
                    continue
                seen.add(canonical)
                candidates.append((kind, result.url, result.published_date, result.title, result.snippet))
                if len(candidates) >= settings.max_pages_per_company:
                    break
            if len(candidates) >= settings.max_pages_per_company:
                break

        candidates = candidates[:settings.max_pages_per_company]

        developments = []
        for kind, url, published_date, title, snippet in candidates:
            page = self.fetcher.fetch(url, fallback_title=title, fallback_snippet=snippet, published_date=published_date)
            if not page:
                page = Page(url=url, title=title, text=f"{title}\n\n{snippet}", published_date=published_date, discovery_snippet=snippet)
                if len(page.text) < 80:
                    fetch_failures += 1
                    continue
            page.published_date = published_date
            page.discovery_snippet = snippet
            if not _entity_match(company, domain, url, page.title, snippet, page.text):
                rejected_entities += 1
                continue
            llm_candidates += 1
            extracted = self.llm.extract(company, domain, kind, page, window_from, window_to)
            for development in extracted:
                if window_from <= development.date <= window_to:
                    developments.append(development)

        developments = _dedupe(developments)

        if search_hits == 0 and not first_party_count:
            warnings.append("Discovery channels returned no results for the selected queries.")
        if self.searcher.provider_status:
            warnings.append("Discovery diagnostics: " + "; ".join(f"{name}: {status}" for name, status in self.searcher.provider_status.items()))
        if rejected_entities:
            warnings.append(f"Rejected {rejected_entities} search candidates as unrelated to the target company.")
        if llm_candidates:
            warnings.append(f"Validated {llm_candidates} company-specific candidates with the evidence model.")
        if first_party_count:
            warnings.append(f"Discovered {first_party_count} first-party pages directly from the company domain.")
        if candidates and fetch_failures == len(candidates):
            warnings.append("Search results were found, but none of the source pages or discovery snippets contained enough evidence to analyze.")
        if self.llm.attempts and self.llm.failures == self.llm.attempts:
            warnings.append(f"LLM extraction failed on all {self.llm.attempts} source attempts. Last error: {self.llm.last_error}")
        elif self.llm.failures:
            warnings.append(f"LLM extraction failed on {self.llm.failures} of {self.llm.attempts} source attempts. Last error: {self.llm.last_error}")
        if not settings.openai_api_key:
            warnings.append("OPENAI_API_KEY is not configured; research sources were discovered but LLM extraction is disabled.")
        if not candidates:
            warnings.append("No research candidates were discovered. Try a company domain or LinkedIn URL.")

        operational_failure = bool(self.llm.attempts and self.llm.failures == self.llm.attempts) or (bool(candidates) and fetch_failures == len(candidates))
        status = "failed" if not candidates and search_hits == 0 else ("partial" if operational_failure else "complete")

        return CompanyResult(
            company=company,
            domain=domain,
            research_window_from=window_from,
            research_window_to=window_to,
            developments=developments,
            sources_scanned=len(candidates),
            source_urls=[item[1] for item in candidates],
            warnings=warnings,
            status=status,
        )
