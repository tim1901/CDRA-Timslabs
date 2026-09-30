import json
import logging
from openai import OpenAI
from ..models.schemas import Development

logger = logging.getLogger(__name__)

SIGNAL_DEFINITIONS = {
    "leadership": "A named executive or senior leader was appointed, departed, promoted, resigned, or otherwise changed roles.",
    "ma": "An acquisition, merger, divestiture, or strategic investment involving the target company was announced or completed.",
    "news": "A material company-specific announcement that does not fit a more specific signal.",
    "transformation": "The target company itself is carrying out a material AI, digital, ERP, CRM, automation, data, or operating-model transformation.",
    "partnerships": "The target company entered a formal strategic partnership, alliance, or collaboration.",
    "funding": "The target company raised funding, financing, or received a material investment.",
    "product": "The target company launched, released, or materially changed a product, service, or platform.",
    "expansion": "The target company expanded into a new market, geography, office, facility, or materially increased its operating footprint.",
    "procurement": "The target company issued an RFP/tender or won/awarded a material contract.",
    "hiring": "The target company announced meaningful hiring, recruitment expansion, or a material talent initiative.",
    "restructuring": "The target company announced layoffs, reorganization, restructuring, or a material operating-model change.",
    "regulatory": "The target company received, faced, or announced a material regulatory approval, ruling, investigation, or compliance action.",
}

SYSTEM = """You are CDRA, an evidence-first company development research agent.

Your job is to reject false positives, not to force every search result into a requested category.

A result qualifies only when the supplied title, snippet, publisher text, or source metadata provides evidence that the EVENT IS ABOUT THE TARGET COMPANY. A source about a competitor, partner, customer, unrelated company, generic concept, industry trend, Wikipedia page, or another company's product must be rejected.

The requested category is a SEARCH HINT, not a classification instruction. Determine the correct signal from the evidence. Never label something leadership merely because the search requested leadership. Leadership requires an actual named senior-personnel change.

Never invent dates, people, transactions, URLs, or claims. Keep the event within the supplied research window. Do not treat generic commentary or industry trends as company developments.

Return JSON only. Use confidence to represent evidence quality, not enthusiasm. If the company match or event evidence is weak, return no development."""
    
class LLM:
    def __init__(self, api_key: str | None, model: str):
        self.client = OpenAI(api_key=api_key) if api_key else None
        self.model = model
        self.last_error: str | None = None
        self.attempts = 0
        self.successes = 0
        self.failures = 0

    def extract(self, company: str, domain: str | None, kind: str, page, window_from: str, window_to: str):
        self.attempts += 1
        if not self.client:
            self.last_error = "OPENAI_API_KEY is not configured"
            self.failures += 1
            return []

        definition = SIGNAL_DEFINITIONS.get(kind, "A material company-specific development.")
        prompt = f"""Target company: {company}
Target domain: {domain or "unknown"}
Research window: {window_from} to {window_to}
Search category: {kind}
Search category definition: {definition}

SOURCE URL: {page.url}
SOURCE TITLE: {page.title}
DISCOVERY PUBLICATION DATE: {getattr(page, "published_date", None)}
DISCOVERY SNIPPET: {getattr(page, "discovery_snippet", "")}

SOURCE TEXT:
{page.text}

First decide whether this source is actually about the TARGET COMPANY and whether it describes a MATERIAL DEVELOPMENT. Then classify the event using the evidence, even if that differs from the search category.

Return exactly:
{{"is_about_target_company":true,"is_material_development":true,"type":"{kind}","date":"YYYY-MM-DD","title":"...","summary":"...","evidence":"short exact evidence quote or close factual excerpt","confidence":0.0,"gtm_relevance":"...","related_signals":[]}}

Return an empty developments array when the source is not about the target company, is not a material development, the event type does not meet its definition, or the evidence is insufficient:
{{"developments":[]}}

Rules:
- Do not create a development from a generic product/help page, encyclopedia page, industry trend, or another company's announcement.
- For leadership, name the person and the actual role change.
- For M&A/funding/partnership/product/etc., the event must involve the target company itself.
- The title must describe the target-company event, not a general topic.
- Confidence below 0.60 means the evidence is insufficient; return no development.
- Evidence must come from the supplied source title, text, or discovery snippet."""
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
                if not item.get("date") and getattr(page, "published_date", None):
                    item["date"] = page.published_date
                if not item.get("is_about_target_company") or not item.get("is_material_development"):
                    continue
                if float(item.get("confidence", 0)) < 0.60:
                    continue
                item["source"]={"name": page.title, "url": page.url, "published_date": item.get("date")}
                item.pop("is_about_target_company", None)
                item.pop("is_material_development", None)
                out.append(Development.model_validate(item))
            self.successes += 1
            return out
        except Exception as exc:
            self.failures += 1
            self.last_error = f"{type(exc).__name__}: {str(exc)[:300]}"
            logger.exception("LLM extraction failed for %s [%s]: %s", company, kind, exc)
            return []
