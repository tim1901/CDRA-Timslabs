import json
import logging
import re
from datetime import date
from urllib.parse import urlparse

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

VALID_TYPES = tuple(SIGNAL_DEFINITIONS)
VALID_TYPES_TEXT = ", ".join(VALID_TYPES)


def _source_kind(url: str) -> str:
    path = urlparse(url).path.lower()
    if any(token in path for token in ("/newsroom/", "/press", "/announcement", "/news/")):
        return "first-party newsroom/announcement"
    if any(token in path for token in ("/release-notes", "/changelog", "/releases")):
        return "first-party release notes/changelog"
    if any(token in path for token in ("/blog/", "/resources/", "/academy/", "/help/", "/docs/")):
        return "company content/blog/help"
    return "web source"


SYSTEM = """You are CDRA, an evidence-first company development research agent.

Your task is to identify real, material developments involving ONE target company from a supplied source.

Think in this order:
1. Is the source actually about the target company?
2. Does it describe a concrete, dated, material development or a distinct dated development inside a release-notes/changelog page?
3. What signal type does the evidence support?
4. Is there enough source-grounded evidence to report it?

Reject false positives. The search category is only a retrieval hint and MUST NOT determine the final type.

Valid signal types:
- leadership: named executive/senior leader appointment, departure, promotion, resignation, or role change
- ma: acquisition, merger, divestiture, or strategic investment involving the target
- news: material company-specific announcement that does not fit a more specific type
- transformation: target's material AI/digital/ERP/CRM/automation/data/operating-model transformation
- partnerships: formal strategic partnership, alliance, or collaboration involving the target
- funding: funding, financing, or material investment received by the target
- product: target product/service/platform launch, release, or material change
- expansion: new market, geography, office, facility, or material operating footprint expansion
- procurement: target RFP/tender or material contract award
- hiring: meaningful hiring/recruitment expansion or material talent initiative
- restructuring: layoffs, reorganization, restructuring, or material operating-model change
- regulatory: material regulatory approval, ruling, investigation, or compliance action

Important:
- A source being hosted on the target's domain is NOT by itself proof that the page contains a development.
- Generic help, documentation, encyclopedia, opinion, educational, or evergreen pages are normally NOT developments.
- A company-authored newsroom announcement can be strong primary evidence.
- A release-notes/changelog page may contain MULTIPLE distinct dated product developments. Extract each clearly dated material update that falls inside the research window.
- Do not invent dates. Prefer an explicit event date in the source. If no event date exists, use the discovery publication date only when it clearly represents the publication date of the development.
- Evidence must be supported by the supplied source text/title/snippet.
- Confidence measures evidence quality. Do not report a weakly supported event.
- Return no development when the source is about another company, a generic topic, or lacks a concrete material event.
"""

class LLM:
    def __init__(self, api_key: str | None, model: str):
        self.client = OpenAI(api_key=api_key) if api_key else None
        self.model = model
        self.last_error: str | None = None
        self.attempts = 0
        self.successes = 0
        self.failures = 0

    @staticmethod
    def _parse_json(content: str) -> dict:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, flags=re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(0))

    @staticmethod
    def _normalise_date(value, fallback: str | None) -> str | None:
        candidate = str(value or "").strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
            try:
                date.fromisoformat(candidate)
                return candidate
            except ValueError:
                pass
        if fallback and re.fullmatch(r"\d{4}-\d{2}-\d{2}", fallback):
            return fallback
        return None

    @staticmethod
    def _normalise_type(value: str | None) -> str | None:
        candidate = str(value or "").strip().lower()
        aliases = {
            "partnership": "partnerships",
            "m&a": "ma",
            "acquisition": "ma",
            "mergers": "ma",
            "fundraising": "funding",
            "launch": "product",
            "products": "product",
            "leadership change": "leadership",
            "executive": "leadership",
        }
        candidate = aliases.get(candidate, candidate)
        return candidate if candidate in VALID_TYPES else None

    def extract(self, company: str, domain: str | None, kind: str, page, window_from: str, window_to: str):
        self.attempts += 1
        if not self.client:
            self.last_error = "OPENAI_API_KEY is not configured"
            self.failures += 1
            return []

        source_kind = _source_kind(page.url)
        fallback_date = getattr(page, "published_date", None)
        discovery_snippet = getattr(page, "discovery_snippet", "") or ""

        # Keep the model focused on the evidence-bearing part of a page. This
        # also prevents long help/docs pages from drowning out the actual event.
        source_text = page.text or ""
        if len(source_text) > 18000:
            source_text = source_text[:18000]

        prompt = f"""TARGET COMPANY: {company}
TARGET DOMAIN: {domain or "unknown"}
RESEARCH WINDOW: {window_from} to {window_to}
SEARCH CATEGORY: {kind}
SOURCE KIND: {source_kind}

SOURCE URL: {page.url}
SOURCE TITLE: {page.title}
DISCOVERY PUBLICATION DATE: {fallback_date}
DISCOVERY SNIPPET: {discovery_snippet}

SOURCE TEXT:
{source_text}

Return exactly one JSON object:
{{
  "developments": [
    {{
      "is_about_target_company": true,
      "is_material_development": true,
      "type": "product",
      "date": "YYYY-MM-DD",
      "title": "target-company event",
      "summary": "one or two factual sentences",
      "evidence": "short source-grounded excerpt",
      "confidence": 0.0,
      "gtm_relevance": "specific reason this matters for GTM",
      "related_signals": []
    }}
  ]
}}

Rules:
- The type MUST be one of: {VALID_TYPES_TEXT}.
- Choose type from the evidence, not from SEARCH CATEGORY.
- For leadership, name the person and the actual role change.
- For partnerships, identify the target company and partner and what was announced.
- For product, identify what the target launched/released/changed.
- For M&A, funding, expansion, procurement, hiring, restructuring, or regulatory events, identify the concrete event.
- Do not turn a product description, feature list, customer story, job listing, generic blog post, or industry article into a development unless it explicitly reports a material event.
- If the source contains several clearly dated release-note items, return several developments rather than collapsing them into one.
- Every reported date must be inside {window_from} to {window_to}.
- If the event date is not explicit, use the discovery publication date only when it is clearly tied to the announcement.
- Evidence must be supported by SOURCE TITLE, DISCOVERY SNIPPET, or SOURCE TEXT.
- Confidence below 0.60 means insufficient evidence: omit the item.
- If the source is not about {company}, or no material development is supported, return {{"developments":[]}}.
"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt},
                ],
            )
            content = response.choices[0].message.content or ""
            if not content:
                raise RuntimeError("OpenAI returned an empty response")

            data = self._parse_json(content)
            out = []
            for raw in data.get("developments", []):
                if not isinstance(raw, dict):
                    continue
                if raw.get("is_about_target_company") is False:
                    continue
                if raw.get("is_material_development") is False:
                    continue

                event_date = self._normalise_date(raw.get("date"), fallback_date)
                event_type = self._normalise_type(raw.get("type"))
                confidence = float(raw.get("confidence", 0) or 0)

                if not event_date or not (window_from <= event_date <= window_to):
                    continue
                if not event_type or confidence < 0.60:
                    continue

                title = str(raw.get("title") or "").strip()
                summary = str(raw.get("summary") or "").strip()
                evidence = str(raw.get("evidence") or "").strip()
                gtm_relevance = str(raw.get("gtm_relevance") or "").strip()

                if not title or not summary or not evidence or not gtm_relevance:
                    continue

                item = {
                    "type": event_type,
                    "date": event_date,
                    "title": title[:240],
                    "summary": summary[:1200],
                    "source": {
                        "name": page.title or company,
                        "url": page.url,
                        "published_date": event_date,
                    },
                    "evidence": evidence[:700],
                    "confidence": min(1.0, max(0.0, confidence)),
                    "gtm_relevance": gtm_relevance[:700],
                    "related_signals": [
                        str(signal).strip()
                        for signal in (raw.get("related_signals") or [])
                        if str(signal).strip()
                    ][:8],
                }

                try:
                    out.append(Development.model_validate(item))
                except Exception as exc:
                    logger.warning("Skipping invalid LLM development for %s: %s", company, exc)

            self.successes += 1
            return out
        except Exception as exc:
            self.failures += 1
            self.last_error = f"{type(exc).__name__}: {str(exc)[:300]}"
            logger.exception("LLM extraction failed for %s [%s]: %s", company, kind, exc)
            return []
