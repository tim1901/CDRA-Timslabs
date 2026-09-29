import logging
from urllib.parse import quote, urlparse, parse_qs, unquote
import httpx
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

logger = logging.getLogger(__name__)

class SearchResult:
    def __init__(self, title: str, url: str, snippet: str = "", published_date: str | None = None):
        self.title, self.url, self.snippet, self.published_date = title, url, snippet, published_date

class Searcher:
    def __init__(self, client: httpx.Client, max_results: int = 6):
        self.client = client
        self.max_results = max_results
        self.provider_status: dict[str, str] = {}

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

    def _parse_rss(self, xml: str) -> list[SearchResult]:
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
                ))
        return out

    def _request(self, provider: str, url: str, accept: str = "text/html,application/xhtml+xml") -> str | None:
        try:
            response = self.client.get(
                url,
                headers={
                    "Accept": accept,
                    "User-Agent": "CDRA/1.0 (+https://cdra-timslabs.vercel.app)",
                },
                timeout=12.0,
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
            results = self._parse_rss(xml)
            self.provider_status["Google News RSS"] = f"ok ({len(results)} results)"
            logger.info("Google News RSS returned %d results for query: %s", len(results), query)
            return results
        except Exception as exc:
            self.provider_status["Google News RSS"] = f"parse error: {type(exc).__name__}: {str(exc)[:160]}"
            logger.warning("Google News RSS parse failed: %s", exc)
            return []

    def search_bing_rss(self, query: str) -> list[SearchResult]:
        url = "https://www.bing.com/search?format=rss&q=" + quote(query)
        xml = self._request("Bing RSS", url, "application/rss+xml,application/xml,text/xml")
        if not xml:
            return []
        try:
            results = self._parse_rss(xml)
            self.provider_status["Bing RSS"] = f"ok ({len(results)} results)"
            logger.info("Bing RSS returned %d results for query: %s", len(results), query)
            return results
        except Exception as exc:
            self.provider_status["Bing RSS"] = f"parse error: {type(exc).__name__}: {str(exc)[:160]}"
            logger.warning("Bing RSS parse failed: %s", exc)
            return []

    def search(self, query: str) -> list[SearchResult]:
        # RSS providers are the critical path. Avoid DuckDuckGo HTML endpoints
        # because they frequently time out from hosted environments such as Render.
        for method in (self.search_google_news_rss, self.search_bing_rss):
            results = method(query)
            if results:
                return results
        logger.warning("No search results for query: %s | providers: %s", query, self.provider_status)
        return []
