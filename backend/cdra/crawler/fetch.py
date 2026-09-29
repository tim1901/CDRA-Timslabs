from urllib.parse import urlparse
import httpx
import trafilatura
from bs4 import BeautifulSoup

class Page:
    def __init__(
        self,
        url: str,
        title: str,
        text: str,
        published_date: str | None = None,
        discovery_snippet: str = "",
    ):
        self.url = url
        self.title = title
        self.text = text
        self.published_date = published_date
        self.discovery_snippet = discovery_snippet

class Fetcher:
    def __init__(self, client: httpx.Client):
        self.client = client

    def fetch(
        self,
        url: str,
        fallback_title: str = "",
        fallback_snippet: str = "",
        published_date: str | None = None,
    ) -> Page | None:
        try:
            r = self.client.get(url, follow_redirects=True)
            r.raise_for_status()
            if "text/html" not in r.headers.get("content-type", ""):
                return None
            html = r.text[:3_000_000]
            extracted = trafilatura.extract(
                html,
                include_links=True,
                include_tables=True,
                favor_precision=True,
            ) or ""
            soup = BeautifulSoup(html, "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else urlparse(url).netloc
            if len(extracted) < 250:
                extracted = soup.get_text(" ", strip=True)

            # Preserve discovery metadata because RSS search results can contain
            # useful evidence even when the publisher page is partially rendered.
            metadata = " ".join(x for x in [fallback_title, fallback_snippet] if x).strip()
            combined = extracted[:30_000]
            if metadata and metadata.lower() not in combined.lower():
                combined = (metadata + "\n\n" + combined).strip()

            return Page(
                url,
                (title or fallback_title or urlparse(url).netloc)[:300],
                combined,
                published_date,
                fallback_snippet,
            )
        except Exception:
            return None
