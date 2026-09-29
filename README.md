# CDRA by Timslabs

Company Development Research Agent — a public portfolio product that researches recent company developments and turns source-backed changes into GTM intelligence.

## Stack
- Next.js + Tailwind frontend
- FastAPI Python backend
- httpx + DuckDuckGo HTML discovery
- Trafilatura + BeautifulSoup extraction
- OpenAI-compatible LLM extraction/reasoning
- No database
- CSV single/batch research

## Local setup

### Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# add OPENAI_API_KEY
python run.py
```
API: http://localhost:8000

### Frontend
```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```
Frontend: http://localhost:3000

## API
`POST /research`
```json
{"company":"acme.com","lookback_months":6,"research_types":["leadership","news","transformation"]}
```

`POST /research/batch`
```json
{"companies":["acme.com","example.com"],"lookback_months":6,"research_types":["leadership","news"]}
```

`POST /research/csv` accepts a multipart CSV and supports `company_name`, `company`, `domain`, or `linkedin_url` columns.

## Important production note
The built-in search layer uses public HTML search discovery and direct HTTP fetching. It is intentionally API-light, but aggressive crawling must respect robots.txt, site terms, rate limits, copyright, and anti-bot controls. For production scale, add a compliant search provider or first-party source connectors rather than bypassing protections.
