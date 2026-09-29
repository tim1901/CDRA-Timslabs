import json
from openai import OpenAI
from ..models.schemas import Development

SYSTEM = """You are CDRA, an evidence-first company development research agent. Extract only developments supported by the supplied source text. Never invent dates, people, transactions, URLs, or claims. A time-windowed result must have an explicit publication/announcement date. Separate factual evidence from GTM interpretation. Return JSON only."""

class LLM:
    def __init__(self, api_key: str | None, model: str):
        self.client = OpenAI(api_key=api_key) if api_key else None
        self.model = model

    def extract(self, company: str, kind: str, page, window_from: str, window_to: str):
        if not self.client:
            return []
        prompt = f"""Company: {company}\nRequested category: {kind}\nWindow: {window_from} to {window_to}\nURL: {page.url}\nTitle: {page.title}\n\nSOURCE TEXT:\n{page.text}\n\nReturn {{\"developments\":[{{\"type\":\"{kind}\",\"date\":\"YYYY-MM-DD\",\"title\":\"...\",\"summary\":\"...\",\"evidence\":\"short exact evidence quote or close factual excerpt\",\"confidence\":0.0,\"gtm_relevance\":\"...\",\"related_signals\":[]}}]}}. If no qualifying development exists, return an empty list. Only use information present in the source."""
        try:
            response = self.client.chat.completions.create(
                model=self.model, temperature=0,
                response_format={"type":"json_object"},
                messages=[{"role":"system","content":SYSTEM},{"role":"user","content":prompt}]
            )
            data = json.loads(response.choices[0].message.content)
            out=[]
            for item in data.get("developments", []):
                item["source"]={"name": page.title, "url": page.url}
                out.append(Development.model_validate(item))
            return out
        except Exception:
            return []
