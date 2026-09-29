from urllib.parse import urlparse
import httpx
import trafilatura
from bs4 import BeautifulSoup

class Page:
    def __init__(self, url: str, title: str, text: str):
        self.url, self.title, self.text = url, title, text

class Fetcher:
    def __init__(self, client: httpx.Client):
        self.client = client

    def fetch(self, url: str) -> Page | None:
        try:
            r = self.client.get(url, follow_redirects=True)
            r.raise_for_status()
            if "text/html" not in r.headers.get("content-type", ""):
                return None
            html = r.text[:3_000_000]
            extracted = trafilatura.extract(html, include_links=True, include_tables=True, favor_precision=True) or ""
            soup = BeautifulSoup(html, "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else urlparse(url).netloc
            if len(extracted) < 250:
                extracted = soup.get_text(" ", strip=True)
            return Page(url, title[:300], extracted[:30_000])
        except Exception:
            return None
