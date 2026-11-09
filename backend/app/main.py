from contextlib import asynccontextmanager

import mimetypes
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import router as api_router
from app.config import get_config
from app.database import init_db
from app.workers import job_runner
from app.workers.scan_loop import scan_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    job_runner.recover()          # pick up jobs a previous process left behind
    if get_config().autoscan:
        scan_loop.start()
    yield
    scan_loop.stop()
    job_runner.shutdown()


app = FastAPI(
    title="Scientific Data Ingestion & Workflow Orchestration (local simulation)",
    description=("Local simulation of a version-aware scientific data ingestion pipeline. NFS = folder, S3 = folder, "
                 "DynamoDB/OpenSearch = SQLite, AWS Batch/miniWDL = in-process workflow engine, "
                 "InterOp/FastQC = simulators. Nothing here talks to AWS."),
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(api_router)


@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok", "data_dir": str(get_config().data_dir), "simulated": True}


