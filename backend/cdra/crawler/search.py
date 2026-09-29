import logging
import re
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

    def _normalise_url(self, href: str) -> str | None:
        if not href:
            return None
        href = href.strip()
        if href.startswith("//"):
            href = "https:" + href
        if href.startswith("/"):
            href = "https://html.duckduckgo.com" + href
        # DuckDuckGo may return redirect links containing the real URL in uddg.
        try:
            parsed = urlparse(href)
            if "duckduckgo.com" in parsed.netloc:
                target = parse_qs(parsed.query).get("uddg", [None])[0]
                if target:
                    href = unquote(target)
        except Exception:
            pass
        if href.startswith(("http://", "https://")):
            return href
        return None

    def _parse_duckduckgo(self, html: str) -> list[SearchResult]:
        soup = BeautifulSoup(html, "html.parser")
        out = []
        # Current DDG HTML results.
        anchors = soup.select("a.result__a")
        # Fallback selectors for DDG markup changes.
        if not anchors:
            anchors = soup.select("a[data-testid='result-title-a'], a.result-link")
        for a in anchors[: self.max_results]:
            href = self._normalise_url(a.get("href"))
            title = a.get_text(" ", strip=True)
            if not href or not title:
                continue
            parent = a.find_parent(class_=re.compile(r"result", re.I))
            snippet = parent.get_text(" ", strip=True)[:500] if parent else ""
            out.append(SearchResult(title, href, snippet))
        return out

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
                out.append(SearchResult(title, href, BeautifulSoup(snippet, "html.parser").get_text(" ", strip=True)[:500], published_date))
        return out

    def _request(self, url: str, accept: str = "text/html,application/xhtml+xml") -> str | None:
        try:
            r = self.client.get(url, headers={"Accept": accept, "Referer": "https://www.google.com/"})
            r.raise_for_status()
            return r.text
        except Exception as exc:
            logger.warning("Search request failed for %s: %s", url.split("?")[0], exc)
            return None

    def search_duckduckgo(self, query: str) -> list[SearchResult]:
        url = "https://html.duckduckgo.com/html/?q=" + quote(query)
        html = self._request(url)
        if not html:
            return []
        return self._parse_duckduckgo(html)

    def search_duckduckgo_lite(self, query: str) -> list[SearchResult]:
        url = "https://lite.duckduckgo.com/lite/?q=" + quote(query)
        html = self._request(url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out = []
        for a in soup.select("a.result-link")[: self.max_results]:
            href = self._normalise_url(a.get("href"))
            title = a.get_text(" ", strip=True)
            if href and title:
                out.append(SearchResult(title, href))
        return out

    def search_bing_rss(self, query: str) -> list[SearchResult]:
        url = "https://www.bing.com/search?format=rss&q=" + quote(query)
        xml = self._request(url, accept="application/rss+xml,application/xml,text/xml")
        if not xml:
            return []
        try:
            return self._parse_rss(xml)
        except Exception:
            return []

    def search_google_news_rss(self, query: str) -> list[SearchResult]:
        # Google News exposes a public RSS search feed; no API key is required.
        url = (
            "https://news.google.com/rss/search?q=" + quote(query)
            + "&hl=en-US&gl=US&ceid=US:en"
        )
        xml = self._request(url, accept="application/rss+xml,application/xml,text/xml")
        if not xml:
            return []
        try:
            return self._parse_rss(xml)
        except Exception as exc:
            logger.warning("Google News RSS parse failed: %s", exc)
            return []

    def search(self, query: str) -> list[SearchResult]:
        # Try several public discovery surfaces. We do not depend on a paid search API.
        for method in (
            self.search_google_news_rss,
            self.search_duckduckgo,
            self.search_duckduckgo_lite,
            self.search_bing_rss,
        ):
            results = method(query)
            if results:
                return results
        return []
