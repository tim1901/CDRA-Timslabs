import logging
from urllib.parse import quote, urlparse, parse_qs, unquote, urljoin
import httpx
from parallel import Parallel
from ..config import settings
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

logger = logging.getLogger(__name__)


class SearchResult:
    def __init__(
        self,
        title: str,
        url: str,
        snippet: str = "",
        published_date: str | None = None,
        source_type: str = "web",
    ):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.published_date = published_date
        self.source_type = source_type


class Searcher:
    def __init__(self, client: httpx.Client, max_results: int = 6):
        self.client = client
        self.max_results = max_results
        self.provider_status: dict[str, str] = {}
        self.parallel = None
        if settings.parallel_api_key:
            self.parallel = Parallel(
                api_key=settings.parallel_api_key,
                timeout=max(30, settings.request_timeout),
                max_retries=2,
            )

    def _normalise_url(self, href: str) -> str | None:
        if not href:
            return None
        href = href.strip()
        if href.startswith("//"):
            href = "https:" + href
        try:
            parsed = urlparse(href)
            if "duckduckgo.com" in parsed.netloc:
                target = parse_qs(parsed.query).get("uddg", [None])[0]
                if target:
                    href = unquote(target)
            elif href.startswith("/"):
                href = "https://news.google.com" + href
        except Exception:
            pass
        if href.startswith(("http://", "https://")):
            return href
        return None

    def _parse_rss(self, xml: str, source_type: str) -> list[SearchResult]:
        out = []
        root = ET.fromstring(xml)
        for item in root.findall(".//item")[: self.max_results]:
            title = item.findtext("title", default="").strip()
            href = item.findtext("link", default="").strip()
            snippet = item.findtext("description", default="").strip()
            pub_date = item.findtext("pubDate", default="").strip()
            published_date = None
            if pub_date:
                try:
                    published_date = parsedate_to_datetime(pub_date).date().isoformat()
                except Exception:
                    published_date = None
            href = self._normalise_url(href)
            if href and title:
                out.append(SearchResult(
                    title,
                    href,
                    BeautifulSoup(snippet, "html.parser").get_text(" ", strip=True)[:500],
                    published_date,
                    source_type,
                ))
        return out

    def _request(
        self,
        provider: str,
        url: str,
        accept: str = "text/html,application/xhtml+xml",
    ) -> str | None:
        try:
            response = self.client.get(
                url,
                headers={
                    "Accept": accept,
                    "User-Agent": "CDRA/1.0 (+https://cdra-timslabs.vercel.app)",
                },
                timeout=12.0,
                follow_redirects=True,
            )
            response.raise_for_status()
            self.provider_status[provider] = f"ok ({response.status_code})"
            return response.text
        except Exception as exc:
            self.provider_status[provider] = f"error: {type(exc).__name__}: {str(exc)[:160]}"
            logger.warning("Search provider %s failed for %s: %s", provider, url.split("?")[0], exc)
            return None

    def search_google_news_rss(self, query: str) -> list[SearchResult]:
        url = (
            "https://news.google.com/rss/search?q=" + quote(query)
            + "&hl=en-US&gl=US&ceid=US:en"
        )
        xml = self._request("Google News RSS", url, "application/rss+xml,application/xml,text/xml")
        if not xml:
            return []
        try:
            results = self._parse_rss(xml, "news")
            self.provider_status["Google News RSS"] = f"ok ({len(results)} results)"
            logger.info("Google News RSS returned %d results for query: %s", len(results), query)
            return results
        except Exception as exc:
            self.provider_status["Google News RSS"] = f"parse error: {type(exc).__name__}: {str(exc)[:160]}"
            logger.warning("Google News RSS parse failed: %s", exc)
            return []

    def search_bing_rss(self, query: str) -> list[SearchResult]:
        url = "https://www.bing.com/search?format=rss&q=" + quote(query)
        xml = self._request("Bing Web RSS", url, "application/rss+xml,application/xml,text/xml")
        if not xml:
            return []
        try:
            results = self._parse_rss(xml, "web")
            self.provider_status["Bing Web RSS"] = f"ok ({len(results)} results)"
            logger.info("Bing Web RSS returned %d results for query: %s", len(results), query)
            return results
        except Exception as exc:
            self.provider_status["Bing Web RSS"] = f"parse error: {type(exc).__name__}: {str(exc)[:160]}"
            logger.warning("Bing Web RSS parse failed: %s", exc)
            return []

    def search_parallel(self, query: str) -> list[SearchResult]:
        if not self.parallel:
            return []
        objective = (
            "Find recent, material company-specific developments relevant to B2B GTM research. "
            "Prioritize first-party announcements, newsroom pages, product/release notes and reputable reporting. "
            "Ignore generic pages, unrelated companies, educational content and evergreen pages."
        )
        try:
            response = self.parallel.search(
                objective=objective,
                search_queries=[query],
                mode="advanced",
                max_results=self.max_results,
                max_chars_per_result=5000,
            )
            results = []
            for item in response:
                url = getattr(item, "url", None)
                title = getattr(item, "title", None) or ""
                excerpt = getattr(item, "excerpt", None) or getattr(item, "snippet", None) or ""
                published = getattr(item, "published_date", None) or getattr(item, "publish_date", None)
                if not url or not title:
                    continue
                if hasattr(published, "isoformat"):
                    published = published.isoformat()
                results.append(SearchResult(title, url, str(excerpt)[:5000], published, "parallel"))
            self.provider_status["Parallel Search"] = f"ok ({len(results)} results)"
            logger.info("Parallel Search returned %d results for query: %s", len(results), query)
            return results
        except Exception as exc:
            self.provider_status["Parallel Search"] = f"error: {type(exc).__name__}: {str(exc)[:160]}"
            logger.warning("Parallel Search failed for query %s: %s", query, exc)
            return []

    def task_research(self, company: str, domain: str, window_from: str, window_to: str) -> list[dict]:
        """Run CDRA's full company-development research brief through Parallel Task API."""
        if not self.parallel:
            return []

        prompt = f"""Research the company {company} ({domain}) for all material company developments that occurred between {window_from} and {window_to}.

The goal is to identify evidence-backed developments that could provide useful go-to-market intelligence.

Investigate ALL of the following signal categories:
1. LEADERSHIP — appointments, departures, promotions, resignations, or major role changes involving executives or senior leaders.
2. M&A — acquisitions, mergers, divestitures, strategic investments, minority investments, or companies/assets acquired or sold.
3. NEWS — material company-specific announcements that do not fit a more specific category; exclude generic coverage, opinion, educational content, and articles that merely mention the company.
4. TRANSFORMATION — material AI, digital transformation, automation, CRM, ERP, data, technology, operating-model, or business-process transformation initiatives.
5. PARTNERSHIPS — formal strategic partnerships, alliances, integrations, technology/channel/distribution partnerships, co-selling arrangements, or major commercial collaborations.
6. FUNDING — funding rounds, financing, debt financing, major investments received, recapitalization, IPO-related financing, or other material capital events.
7. PRODUCT — significant product, platform, service, feature, or technology launches, releases, major upgrades, or material changes.
8. EXPANSION — expansion into new countries, geographic markets, industries, customer segments, offices, facilities, regions, or other material market-footprint increases.
9. PROCUREMENT — RFPs, tenders, major procurement initiatives, large contracts awarded to or by the company, or material enterprise purchasing/sourcing activity involving the company.
10. HIRING — meaningful hiring expansions, major recruitment initiatives, new hiring programs, large talent investments, or significant workforce expansion; ignore ordinary individual job postings.
11. RESTRUCTURING — layoffs, workforce reductions, reorganizations, restructuring, business-unit changes, operating-model changes, closures, spin-offs, or other significant organizational changes.
12. REGULATORY — material regulatory approvals, investigations, rulings, enforcement actions, compliance changes, licenses, certifications, or other regulatory events that materially affect the company.

Research requirements:
- Prioritize first-party sources from the company's official website, newsroom, investor relations site, press releases, product documentation, release notes, regulatory filings, and official announcements.
- Then use high-quality independent sources such as Reuters, Bloomberg, Financial Times, TechCrunch, WSJ, major industry publications, and reputable business media.
- Use multiple sources when available to corroborate important developments.
- Do not treat Google News, Bing, search-result pages, aggregators, or social-media posts as final evidence when the underlying article or company announcement can be found.
- Do not include a development simply because the company is mentioned in an article.
- Reject generic articles, educational pages, job boards, directory pages, Wikipedia, opinion pieces, and unrelated companies with similar names.
- Every development must clearly concern {company}.
- Only include developments whose event date falls within {window_from} to {window_to}.
- Prefer the date the event actually occurred or was announced rather than a later update date.
- Do not invent dates, facts, sources, or evidence.
- If no qualifying development exists for a category, return no items for that category.

For every qualifying development, collect: signal_type, event_date, title, concise_summary, what_changed, why_it_matters, gtm_relevance, companies_or_entities_involved, geography, source_url, source_title, source_type, evidence_excerpt, confidence, and corroborating_sources.

For GTM relevance, consider sales strategy, marketing strategy, customer acquisition, market expansion, partnerships/channel strategy, product positioning, pricing/commercial strategy, sales technology, marketing technology, CRM/revenue operations, GTM hiring, competitive positioning, new customer segments, and geographic expansion. Do not assume every development has GTM relevance; explain it only when supported by evidence.

Return only qualifying developments in the requested research window."""

        output_schema = {
            "type": "json",
            "json_schema": {
                "type": "object",
                "properties": {
                    "developments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "signal_type": {"type": "string"},
                                "event_date": {"type": "string"},
                                "title": {"type": "string"},
                                "concise_summary": {"type": "string"},
                                "what_changed": {"type": "string"},
                                "why_it_matters": {"type": "string"},
                                "gtm_relevance": {"type": "string"},
                                "companies_or_entities_involved": {"type": "array", "items": {"type": "string"}},
                                "geography": {"type": "string"},
                                "source_url": {"type": "string"},
                                "source_title": {"type": "string"},
                                "source_type": {"type": "string"},
                                "evidence_excerpt": {"type": "string"},
                                "confidence": {"type": "number"},
                                "corroborating_sources": {"type": "array", "items": {"type": "string"}}
                            },
                            "required": ["signal_type","event_date","title","concise_summary","what_changed","why_it_matters","gtm_relevance","source_url","source_title","source_type","evidence_excerpt","confidence","corroborating_sources"]
                        }
                    }
                },
                "required": ["developments"]
            }
        }
        try:
            run = self.parallel.task_run.create(
                input=prompt,
                processor="core",
                task_spec={"output_schema": output_schema},
            )
            result = self.parallel.task_run.result(run.run_id, api_timeout=1800)
            content = getattr(getattr(result, "output", None), "content", None)
            if hasattr(content, "model_dump"):
                content = content.model_dump()
            elif isinstance(content, str):
                import json
                content = json.loads(content)
            if not isinstance(content, dict):
                raise ValueError("Parallel Task returned no structured object")
            findings = content.get("developments", [])
            if not isinstance(findings, list):
                raise ValueError("Parallel Task returned an invalid developments list")
            self.provider_status["Parallel Task"] = f"ok ({len(findings)} findings)"
            logger.info("Parallel Task returned %d findings for %s", len(findings), domain)
            return findings
        except Exception as exc:
            self.provider_status["Parallel Task"] = f"error: {type(exc).__name__}: {str(exc)[:160]}"
            logger.warning("Parallel Task failed for %s: %s", domain, exc)
            return []

    def search(self, query: str) -> list[SearchResult]:
        # Parallel is the primary web research provider when PARALLEL_API_KEY
        # is configured. RSS providers remain a resilience fallback.
        if self.parallel:
            results = self.search_parallel(query)
            if results:
                return results
        google = self.search_google_news_rss(query)
        bing = self.search_bing_rss(query)
        merged = []
        seen = set()
        for result in google + bing:
            canonical = result.url.split("#", 1)[0].rstrip("/")
            if canonical in seen:
                continue
            seen.add(canonical)
            merged.append(result)
        if not merged:
            logger.warning("No search results for query: %s | providers: %s", query, self.provider_status)
        return merged

    def discover_first_party(self, domain: str, max_pages: int = 16) -> list[SearchResult]:
        """Discover first-party pages directly from the company's domain.

        Uses robots/sitemaps plus relevant navigation links. These pages are
        intentionally separate from news/web search because product, hiring,
        partnership and company announcements often never enter news indexes.
        """
        domain = domain.lower().removeprefix("www.").rstrip("/")
        base = f"https://{domain}"
        urls: list[str] = [f"{base}/"]
        sitemap_candidates = [f"{base}/sitemap.xml", f"{base}/sitemap_index.xml"]

        robots = self._request("First-party robots", f"{base}/robots.txt", "text/plain")
        if robots:
            for line in robots.splitlines():
                if line.lower().startswith("sitemap:"):
                    sitemap_candidates.append(line.split(":", 1)[1].strip())

        for sitemap_url in sitemap_candidates[:5]:
            xml = self._request("First-party sitemap", sitemap_url, "application/xml,text/xml")
            if not xml:
                continue
            try:
                root = ET.fromstring(xml)
                for loc in root.findall(".//{*}loc"):
                    if loc.text:
                        urls.append(loc.text.strip())
            except Exception as exc:
                logger.warning("Sitemap parse failed for %s: %s", sitemap_url, exc)

        homepage = self._request("First-party homepage", base, "text/html,application/xhtml+xml")
        if homepage:
            try:
                soup = BeautifulSoup(homepage, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = urljoin(base + "/", a["href"])
                    parsed = urlparse(href)
                    if parsed.netloc.lower().removeprefix("www.") == domain:
                        urls.append(href.split("#", 1)[0])
            except Exception as exc:
                logger.warning("Homepage link discovery failed for %s: %s", domain, exc)

        keywords = (
            "blog", "news", "press", "announcement", "product", "changelog",
            "career", "jobs", "hiring", "company", "about", "release",
            "integration", "partner", "customer", "resource"
        )
        # Rank candidate URLs before truncating. Sitemap order is often
        # arbitrary, so taking the first N relevant URLs can miss newsroom
        # articles and release-note pages with the strongest evidence.
        ranked = []
        seen = set()
        priority = (
            ("announcement", 100),
            ("newsroom", 100),
            ("press", 95),
            ("news", 90),
            ("release-notes", 90),
            ("changelog", 90),
            ("release", 85),
            ("partner", 75),
            ("product", 70),
            ("company", 60),
            ("about", 50),
            ("career", 40),
            ("jobs", 40),
            ("hiring", 40),
            ("resource", 30),
            ("blog", 25),
        )
        for url in urls:
            parsed = urlparse(url)
            clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
            if clean in seen or not clean.startswith(("http://", "https://")):
                continue
            seen.add(clean)
            path = parsed.path.lower()
            if path == "" or any(k in path for k in keywords):
                score = 0
                for token, weight in priority:
                    if token in path:
                        score = max(score, weight)
                depth = len([part for part in path.split("/") if part])
                score += min(depth, 4)
                ranked.append((score, clean))

        ranked.sort(key=lambda item: item[0], reverse=True)
        unique = [url for _, url in ranked[:max_pages]]

        results = []
        for url in unique:
            title = urlparse(url).path.strip("/").replace("/", " · ") or domain
            results.append(SearchResult(title, url, "", None, "first_party"))
        self.provider_status["First-party discovery"] = f"ok ({len(results)} pages)"
        return results
