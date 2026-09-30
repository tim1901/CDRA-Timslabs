import logging
from urllib.parse import quote, urlparse, parse_qs, unquote, urljoin
import httpx
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

    def search(self, query: str) -> list[SearchResult]:
        # Google News and Bing Web are complementary discovery channels.
        # Google News is not the primary research source; both are merged and
        # deduplicated before source fetching and evidence validation.
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
        unique = []
        seen = set()
        for url in urls:
            parsed = urlparse(url)
            clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
            if clean in seen or not clean.startswith(("http://", "https://")):
                continue
            seen.add(clean)
            path = parsed.path.lower()
            if path == "" or any(k in path for k in keywords):
                unique.append(clean)
            if len(unique) >= max_pages:
                break

        results = []
        for url in unique:
            title = urlparse(url).path.strip("/").replace("/", " · ") or domain
            results.append(SearchResult(title, url, "", None, "first_party"))
        self.provider_status["First-party discovery"] = f"ok ({len(results)} pages)"
        return results
