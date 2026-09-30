import csv, io, logging
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from uuid import uuid4
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .models.schemas import ResearchRequest, BatchResearchRequest, BatchResult
from .agent.research import ResearchAgent

logger = logging.getLogger(__name__)
app=FastAPI(title="CDRA API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.allowed_origins.split(",")], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# In-memory job store: intentionally no database for the portfolio/demo deployment.
# Jobs survive the request lifecycle, but not a Render instance restart.
executor = ThreadPoolExecutor(max_workers=2)
jobs: dict[str, dict] = {}
jobs_lock = Lock()

@app.get("/health")
def health(): return {"status":"ok","service":"cdra"}

def _set_job(job_id: str, **updates):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(updates)

def _run_single(job_id: str, req: ResearchRequest):
    _set_job(job_id, status="running")
    try:
        logger.info("Research job %s started for %s", job_id, req.company_website or req.company)
        result = ResearchAgent().run(req.company or req.company_website or "", req.lookback_months, req.research_types, company_website=req.company_website)
        _set_job(job_id, status="complete", result=result)
        logger.info("Research job %s completed: %s developments, status=%s", job_id, len(result.developments), result.status)
    except Exception as exc:
        logger.exception("Research job %s failed: %s", job_id, exc)
        _set_job(job_id, status="failed", error=f"{type(exc).__name__}: {str(exc)[:500]}")

def _run_batch(job_id: str, req: BatchResearchRequest):
    _set_job(job_id, status="running")
    try:
        logger.info("Batch research job %s started for %d companies", job_id, len(req.companies))
        agent=ResearchAgent()
        results=[agent.run(company, req.lookback_months, req.research_types) for company in req.companies]
        _set_job(job_id, status="complete", result=BatchResult(results=results))
        logger.info("Batch research job %s completed", job_id)
    except Exception as exc:
        logger.exception("Batch research job %s failed: %s", job_id, exc)
        _set_job(job_id, status="failed", error=f"{type(exc).__name__}: {str(exc)[:500]}")

def _submit(fn, *args):
    job_id = uuid4().hex
    with jobs_lock:
        jobs[job_id] = {"status": "queued", "result": None, "error": None}
    executor.submit(fn, job_id, *args)
    logger.info("Queued research job %s", job_id)
    return job_id

@app.post("/research", status_code=202)
def research(req: ResearchRequest):
    return {"job_id": _submit(_run_single, req), "status": "queued"}

@app.get("/research/{job_id}")
def research_status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Research job not found. Jobs are in-memory and may be lost after a server restart.")
    response = {"job_id": job_id, "status": job["status"]}
    if job["status"] == "complete": response["result"] = job["result"]
    elif job["status"] == "failed": response["error"] = job["error"]
    return response

@app.post("/research/batch", status_code=202)
def research_batch(req: BatchResearchRequest):
    return {"job_id": _submit(_run_batch, req), "status": "queued"}

@app.post("/research/csv", status_code=202)
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
