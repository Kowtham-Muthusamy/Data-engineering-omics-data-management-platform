from fastapi import APIRouter

from app.api import audit, dashboard, downstream, runs, s3, samples, sequencer, workflows

router = APIRouter()
for module in (runs, s3, sequencer, samples, workflows, downstream, dashboard, audit):
    router.include_router(module.router)
