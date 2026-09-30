from datetime import date
from typing import Literal
from pydantic import BaseModel, Field, HttpUrl

SignalType = Literal[
    "leadership", "ma", "news", "transformation", "partnerships", "funding",
    "product", "expansion", "procurement", "hiring", "restructuring", "regulatory"
]

class ResearchRequest(BaseModel):
    company: str = Field(default="", max_length=300)
    company_website: str | None = Field(default=None, max_length=500)
    lookback_months: int = Field(default=6, ge=1, le=60)
    research_types: list[SignalType] = Field(default_factory=lambda: [
        "leadership", "ma", "news", "transformation", "partnerships", "funding",
        "product", "expansion"
    ])

class BatchResearchRequest(BaseModel):
    companies: list[str] = Field(min_length=1, max_length=100)
    lookback_months: int = Field(default=6, ge=1, le=60)
    research_types: list[SignalType]

class Source(BaseModel):
    name: str
    url: str
    published_date: str | None = None

class Development(BaseModel):
    type: SignalType
    date: str
    title: str
    summary: str
    source: Source
    evidence: str
    confidence: float = Field(ge=0, le=1)
    gtm_relevance: str
    related_signals: list[str] = []

class CompanyResult(BaseModel):
    company: str
    domain: str | None = None
    research_window_from: str
    research_window_to: str
    developments: list[Development]
    sources_scanned: int
    source_urls: list[str]
    warnings: list[str] = []
    status: Literal["complete", "partial", "failed"] = "complete"

class BatchResult(BaseModel):
    results: list[CompanyResult]
