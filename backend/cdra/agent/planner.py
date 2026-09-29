from datetime import date
from dateutil.relativedelta import relativedelta

QUERIES = {
    "leadership": '"{company}" leadership CEO CRO "VP Sales" appointed joins promoted {year}',
    "ma": '"{company}" acquisition acquired merger investment {year}',
    "news": '"{company}" announces announced launch partnership expansion {year}',
    "transformation": '"{company}" AI "digital transformation" automation ERP CRM modernization {year}',
    "partnerships": '"{company}" partnership partner alliance {year}',
    "funding": '"{company}" funding investment financing raises {year}',
    "product": '"{company}" launches launched "new product" platform {year}',
    "expansion": '"{company}" expands expansion "new market" "new office" {year}',
    "procurement": '"{company}" RFP tender procurement "contract award" {year}',
    "hiring": '"{company}" hiring "new hires" recruitment {year}',
    "restructuring": '"{company}" restructuring layoffs reorganization {year}',
    "regulatory": '"{company}" regulatory regulation compliance approval {year}',
}

def build_queries(company: str, lookback_months: int, types: list[str]) -> list[tuple[str, str]]:
    cutoff = date.today() - relativedelta(months=lookback_months)
    years = str(date.today().year)
    if cutoff.year != date.today().year:
        years = f"{cutoff.year} {date.today().year}"
    return [
        (kind, QUERIES[kind].format(company=company, year=years))
        for kind in types
        if kind in QUERIES
    ]
