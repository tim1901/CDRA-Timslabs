from datetime import date
from dateutil.relativedelta import relativedelta

QUERIES = {
    "leadership": '"{company}" CEO OR CRO OR "Chief" OR "VP Sales" OR appointed OR joins OR promoted {year}',
    "ma": '"{company}" acquisition OR acquired OR merger OR investment {year}',
    "news": '"{company}" announces OR announced OR launch OR partnership OR expansion {year}',
    "transformation": '"{company}" AI OR "digital transformation" OR automation OR ERP OR CRM OR modernization {year}',
    "partnerships": '"{company}" partnership OR partner OR alliance {year}',
    "funding": '"{company}" funding OR investment OR financing OR raises {year}',
    "product": '"{company}" launches OR launched OR "new product" OR platform {year}',
    "expansion": '"{company}" expands OR expansion OR "new market" OR "new office" {year}',
    "procurement": '"{company}" RFP OR tender OR procurement OR "contract award" {year}',
    "hiring": '"{company}" hiring OR "new hires" OR recruitment {year}',
    "restructuring": '"{company}" restructuring OR layoffs OR reorganization {year}',
    "regulatory": '"{company}" regulatory OR regulation OR compliance OR approval {year}',
}


def build_queries(
    company: str,
    lookback_months: int,
    types: list[str],
    domain: str | None = None,
) -> list[tuple[str, str]]:
    """Build company-targeted discovery queries.

    When the user supplies a URL/domain, the domain is the strongest search
    identity. This prevents short/ambiguous brands such as "Apollo" from
    pulling results for unrelated entities such as Apollo Global Management.
    """
    cutoff = date.today() - relativedelta(months=lookback_months)
    years = str(date.today().year)
    if cutoff.year != date.today().year:
        years = f"{cutoff.year} {date.today().year}"

    # Domain-qualified identity is used for external discovery when available.
    # Keep the human-readable company name for first-party site searches.
    search_identity = domain if domain else company

    queries: list[tuple[str, str]] = []
    for kind in types:
        template = QUERIES.get(kind)
        if not template:
            continue

        external = template.format(company=search_identity, year=years)
        queries.append((kind, external))

        if domain:
            first_party = f"site:{domain} {template.format(company=company, year=years)}"
            queries.append((kind, first_party))

    return queries
