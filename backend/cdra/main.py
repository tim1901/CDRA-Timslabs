import csv, io
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from .config import settings
from .models.schemas import ResearchRequest, BatchResearchRequest, BatchResult
from .agent.research import ResearchAgent

app=FastAPI(title="CDRA API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.allowed_origins.split(",")], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
def health(): return {"status":"ok","service":"cdra"}

@app.post("/research")
def research(req: ResearchRequest):
    return ResearchAgent().run(req.company or req.company_website or "", req.lookback_months, req.research_types, company_website=req.company_website)

@app.post("/research/batch")
def research_batch(req: BatchResearchRequest):
    agent=ResearchAgent(); results=[]
    for company in req.companies:
        results.append(agent.run(company, req.lookback_months, req.research_types))
    return BatchResult(results=results)

@app.post("/research/csv")
def research_csv(file: UploadFile=File(...), lookback_months:int=6, research_types:str="leadership,ma,news,transformation,partnerships,funding,product,expansion"):
    if not file.filename or not file.filename.lower().endswith('.csv'):
        raise HTTPException(400,"Please upload a CSV file.")
    raw=(file.file.read()).decode('utf-8-sig')
    rows=list(csv.DictReader(io.StringIO(raw)))
    companies=[]
    for row in rows:
        value=row.get('domain') or row.get('company_name') or row.get('company') or row.get('linkedin_url')
        if value: companies.append(value.strip())
    if not companies: raise HTTPException(400,"CSV needs company_name, company, domain, or linkedin_url.")
    if len(companies)>100: raise HTTPException(400,"Maximum 100 companies per run.")
    types=[x.strip() for x in research_types.split(',') if x.strip()]
    return research_batch(BatchResearchRequest(companies=companies,lookback_months=lookback_months,research_types=types))
