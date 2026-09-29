import json
import logging
from openai import OpenAI
from ..models.schemas import Development

logger = logging.getLogger(__name__)

SYSTEM = """You are CDRA, an evidence-first company development research agent. Extract only developments supported by the supplied source text. Never invent dates, people, transactions, URLs, or claims. A time-windowed result must have an explicit publication/announcement date. Separate factual evidence from GTM interpretation. Return JSON only."""

class LLM:
    def __init__(self, api_key: str | None, model: str):
        self.client = OpenAI(api_key=api_key) if api_key else None
        self.model = model
        self.last_error: str | None = None
        self.attempts = 0
        self.successes = 0
        self.failures = 0

    def extract(self, company: str, kind: str, page, window_from: str, window_to: str):
        self.attempts += 1
        if not self.client:
            self.last_error = "OPENAI_API_KEY is not configured"
            self.failures += 1
            return []

        prompt = f"""Company: {company}\nRequested category: {kind}\nWindow: {window_from} to {window_to}\nURL: {page.url}\nTitle: {page.title}\n\nSOURCE TEXT:\n{page.text}\n\nReturn {{\"developments\":[{{\"type\":\"{kind}\",\"date\":\"YYYY-MM-DD\",\"title\":\"...\",\"summary\":\"...\",\"evidence\":\"short exact evidence quote or close factual excerpt\",\"confidence\":0.0,\"gtm_relevance\":\"...\",\"related_signals\":[]}}]}}. If no qualifying development exists, return an empty list. Only use information present in the source."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                response_format={"type":"json_object"},
                messages=[{"role":"system","content":SYSTEM},{"role":"user","content":prompt}]
            )
            content = response.choices[0].message.content or ""
            if not content:
                raise RuntimeError("OpenAI returned an empty response")
            data = json.loads(content)
            out=[]
            for item in data.get("developments", []):
                item["source"]={"name": page.title, "url": page.url}
                out.append(Development.model_validate(item))
            self.successes += 1
            return out
        except Exception as exc:
            self.failures += 1
            self.last_error = f"{type(exc).__name__}: {str(exc)[:300]}"
            logger.exception("LLM extraction failed for %s [%s]: %s", company, kind, exc)
            return []
