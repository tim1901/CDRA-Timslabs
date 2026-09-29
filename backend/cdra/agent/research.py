from datetime import date
from dateutil.relativedelta import relativedelta
from urllib.parse import urlparse
import httpx
from ..config import settings
from ..crawler.search import Searcher
from ..crawler.fetch import Fetcher
from ..crawler.company import normalize_company
from .planner import build_queries
from .llm import LLM
from ..models.schemas import CompanyResult, Development, Source

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
        warnings=[]; urls=[]; candidates=[]; seen=set(); search_hits=0; fetch_failures=0
        for kind, query in build_queries(company, lookback_months, types):
            results = self.searcher.search(query)
            search_hits += len(results)
            for r in results:
                if r.url in seen: continue
                seen.add(r.url); urls.append(r.url); candidates.append((kind,r.url,r.published_date))
                if len(urls) >= settings.max_pages_per_company: break
            if len(urls) >= settings.max_pages_per_company: break
        developments=[]
        for kind,url,published_date in candidates:
            page=self.fetcher.fetch(url)
            if not page or len(page.text)<250:
                fetch_failures += 1
                continue
            page.published_date = published_date
            extracted=self.llm.extract(company,kind,page,window_from,window_to)
            for d in extracted:
                d.source.published_date=d.date
                if window_from <= d.date <= window_to:
                    developments.append(d)
        # deterministic dedupe by type/title/date
        unique={}
        for d in developments:
            unique[(d.type,d.date,d.title.lower())]=d
        developments=sorted(unique.values(), key=lambda x:x.date, reverse=True)
        if search_hits == 0:
            warnings.append("Search providers returned no results for the selected queries.")
        if candidates and fetch_failures == len(candidates):
            warnings.append("Search results were found, but none of the source pages could be fetched.")
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
