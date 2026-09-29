from datetime import date
from dateutil.relativedelta import relativedelta

TITLES = [
    "CEO", "Chief Executive Officer", "CFO", "Chief Financial Officer", "COO",
    "Chief Operating Officer", "CTO", "Chief Technology Officer", "CIO", "Chief Information Officer",
    "CMO", "Chief Marketing Officer", "CRO", "Chief Revenue Officer", "VP Sales", "VP Revenue",
    "VP Marketing", "VP Growth", "VP Engineering", "Head of Sales", "Head of Revenue", "Head of Marketing"
]

QUERIES = {
    "leadership": '"{company}" ({titles}) (appointed OR joins OR named OR promoted) after:{after}',
    "ma": '"{company}" (acquisition OR acquired OR merger OR "strategic investment") after:{after}',
    "news": '"{company}" (announces OR announced OR launches OR partnership OR expansion) after:{after}',
    "transformation": '"{company}" (AI OR "digital transformation" OR automation OR ERP OR CRM OR modernization) after:{after}',
    "partnerships": '"{company}" (partnership OR partner OR alliance) after:{after}',
    "funding": '"{company}" (funding OR investment OR financing OR raises) after:{after}',
    "product": '"{company}" (launches OR launched OR "new product" OR platform) after:{after}',
    "expansion": '"{company}" (expands OR expansion OR "new market" OR "new office") after:{after}',
    "procurement": '"{company}" (RFP OR tender OR procurement OR "contract award") after:{after}',
    "hiring": '"{company}" (hiring OR "new hires" OR recruitment) after:{after}',
    "restructuring": '"{company}" (restructuring OR layoffs OR reorganization) after:{after}',
    "regulatory": '"{company}" (regulatory OR regulation OR compliance OR approval) after:{after}',
}

def build_queries(company: str, lookback_months: int, types: list[str]) -> list[tuple[str,str]]:
    after = (date.today() - relativedelta(months=lookback_months)).isoformat()
    title_string = ' OR '.join(f'"{t}"' for t in TITLES)
    return [(kind, QUERIES[kind].format(company=company, titles=title_string, after=after)) for kind in types if kind in QUERIES]
