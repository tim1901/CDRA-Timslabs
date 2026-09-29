import re
from urllib.parse import quote, urlparse
import httpx
from bs4 import BeautifulSoup

class SearchResult:
    def __init__(self, title: str, url: str, snippet: str = ""):
        self.title, self.url, self.snippet = title, url, snippet

class Searcher:
    def __init__(self, client: httpx.Client, max_results: int = 6):
        self.client = client
        self.max_results = max_results

    def search_duckduckgo(self, query: str) -> list[SearchResult]:
        url = "https://html.duckduckgo.com/html/?q=" + quote(query)
        try:
            r = self.client.get(url)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            out = []
            for a in soup.select("a.result__a")[: self.max_results]:
                href = a.get("href")
                title = a.get_text(" ", strip=True)
                if href and href.startswith("http"):
                    parent = a.find_parent("div", class_="result")
                    snippet = parent.get_text(" ", strip=True)[:500] if parent else ""
                    out.append(SearchResult(title, href, snippet))
            return out
        except Exception:
            return []

    def search(self, query: str) -> list[SearchResult]:
        return self.search_duckduckgo(query)
