from datetime import date
from dateutil.relativedelta import relativedelta
from urllib.parse import urlparse
from difflib import SequenceMatcher
import re
import httpx
from ..config import settings
from ..crawler.search import Searcher
from ..crawler.fetch import Fetcher
from ..crawler.company import normalize_company
from .planner import build_queries
from .llm import LLM
from ..models.schemas import CompanyResult

def _tokens(value: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9]+", value.lower()) if len(x) > 2}

def _entity_match(company: str, domain: str | None, url: str, title: str, snippet: str, text: str) -> bool:
    corpus = " ".join([title, snippet, text[:12000]]).lower()
    company_tokens = _tokens(company)
    if not company_tokens:
        return True
    phrase = " ".join(sorted(company_tokens))
    compact = re.sub(r"[^a-z0-9]+", " ", company.lower()).strip()
    normalized_corpus = re.sub(r"[^a-z0-9]+", " ", corpus)
    if compact and compact in normalized_corpus:
        return True
    matched = sum(1 for token in company_tokens if re.search(rf"\b{re.escape(token)}\b", normalized_corpus))
    if len(company_tokens) == 1:
        return matched == 1
    if matched >= max(2, len(company_tokens) // 2 + 1):
        return True
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if domain:
        target_host = domain.lower().removeprefix("www.")
        if host == target_host or host.endswith("." + target_host):
            return True
    return False

def _event_key(d):
    words = _tokens(d.title)
    return (d.type, d.date, frozenset(words))

def _dedupe(developments):
    kept=[]
    for d in sorted(developments, key=lambda x: (x.confidence, x.date), reverse=True):
        duplicate=False
        for existing in kept:
            if d.type != existing.type:
                continue
            similarity=SequenceMatcher(None, d.title.lower(), existing.title.lower()).ratio()
            overlap=len(_tokens(d.title) & _tokens(existing.title)) / max(1, len(_tokens(d.title) | _tokens(existing.title)))
            same_event = similarity >= 0.72 or overlap >= 0.55
            close_date = abs((date.fromisoformat(d.date) - date.fromisoformat(existing.date)).days) <= 14
            if same_event and close_date:
                duplicate=True
                break
        if not duplicate:
            kept.append(d)
    return sorted(kept, key=lambda x: x.date, reverse=True)

class ResearchAgent:
    def __init__(self):
        headers={"User-Agent": settings.user_agent, "Accept-Language":"en-US,en;q=0.8"}
        self.client=httpx.Client(headers=headers, timeout=settings.request_timeout)
        self.searcher=Searcher(self.client, settings.max_sources_per_query)
        self.fetcher=Fetcher(self.client)
        self.llm=LLM(settings.openai_api_key, settings.openai_model)

    def run(self, company_input: str, lookback_months: int, types: list[str]) -> CompanyResult:
        company, domain = normalize_company(company_input)
        window_from=(date.today()-relativedelta(months=lookback_months)).isoformat()
        window_to=date.today().isoformat()
        warnings=[]; urls=[]; candidates=[]; seen=set(); search_hits=0; fetch_failures=0; rejected_entities=0
        for kind, query in build_queries(company, lookback_months, types):
            results = self.searcher.search(query)
            search_hits += len(results)
            for r in results:
                if r.url in seen: continue
                seen.add(r.url); urls.append(r.url); candidates.append((kind,r.url,r.published_date,r.title,r.snippet))
                if len(urls) >= settings.max_pages_per_company: break
            if len(urls) >= settings.max_pages_per_company: break

        developments=[]
        for kind,url,published_date,title,snippet in candidates:
            page=self.fetcher.fetch(url, fallback_title=title, fallback_snippet=snippet, published_date=published_date)
            if not page:
                from .fetch import Page
                page = Page(url=url,title=title,text=f"{title}\n\n{snippet}",published_date=published_date,discovery_snippet=snippet)
                if len(page.text) < 80:
                    fetch_failures += 1
                    continue
            page.published_date = published_date
            page.discovery_snippet = snippet

            # Cheap deterministic entity gate before spending an LLM call.
            if not _entity_match(company, domain, url, page.title, snippet, page.text):
                rejected_entities += 1
                continue

            extracted=self.llm.extract(company, domain, kind, page, window_from, window_to)
            for d in extracted:
                if window_from <= d.date <= window_to:
                    developments.append(d)

        developments=_dedupe(developments)

        if search_hits == 0:
            warnings.append("Search providers returned no results for the selected queries.")
            if self.searcher.provider_status:
                warnings.append("Search provider diagnostics: " + "; ".join(f"{name}: {status}" for name, status in self.searcher.provider_status.items()))
        if rejected_entities:
            warnings.append(f"Rejected {rejected_entities} search candidates because they did not appear to concern the target company.")
        if candidates and fetch_failures == len(candidates):
            warnings.append("Search results were found, but none of the source pages or discovery snippets contained enough evidence to analyze.")
        if self.llm.attempts and self.llm.failures == self.llm.attempts:
            warnings.append(f"LLM extraction failed on all {self.llm.attempts} source attempts. Last error: {self.llm.last_error}")
        elif self.llm.failures:
            warnings.append(f"LLM extraction failed on {self.llm.failures} of {self.llm.attempts} source attempts. Last error: {self.llm.last_error}")
        if not settings.openai_api_key:
            warnings.append("OPENAI_API_KEY is not configured; research sources were discovered but LLM extraction is disabled.")
        if not candidates:
            warnings.append("No search results were discovered. Try a company domain or LinkedIn URL.")
        status="complete" if developments or not candidates else "partial"
        return CompanyResult(company=company,domain=domain,research_window_from=window_from,research_window_to=window_to,developments=developments,sources_scanned=len(urls),source_urls=urls,warnings=warnings,status=status)
