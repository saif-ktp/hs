"""HS — Health & Safety Issues Dashboard. App entrypoint.

Upload an issues-export CSV, get back the aggregates the dashboard charts
need. PDF export lives in export.py (routes) and report.py (layout);
shared CSV parsing lives in core.py.

Run with:  uvicorn main:app --host 0.0.0.0 --port 8000
"""

import os

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from core import HERE, parse_issues_csv
from export import router as export_router

app = FastAPI(title="HS — Health & Safety Issues Dashboard")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(export_router)


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "index.html"))


@app.post("/api/upload")
async def upload_csv(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        return parse_issues_csv(raw)
    except ValueError as e:
        raise HTTPException(400, str(e))
