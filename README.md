# Version-Aware Scientific Data Ingestion & Workflow Orchestration (local simulation)

A fully local, working simulation of a scientific data ingestion pipeline. **Nothing here talks to AWS.**

| Real-world component | Local simulation |
| --- | --- |
| NFS source drive | folder `local_data/nfs_source/` |
| Amazon S3 | folder `local_data/s3_bucket/` + SQLite bookkeeping |
| DynamoDB (state tracking) | SQLite tables (`runs`, `samples`, `processing_attempts`, ...) |
| OpenSearch (metadata search) | SQLite `search_index` table, kept separate from state |
| AWS Batch + miniWDL | in-process workflow engine (thread pool, 9 steps) |
| InterOp / FastQC | deterministic simulators (clearly labelled as simulated) |

```
NFS folder -> scheduled sequencer -> version detection + state tracking -> S3 folder
          -> (SQLite state, SQLite search) -> workflow -> InterOp + FastQC sims -> quality gate
          -> PASS: downstream application      FAIL: blocked (enforced by the backend)
```

## Run it

Requirements: Python 3.11+, Node.js 20+ (only for the UI).

```powershell
.\start.ps1            # creates the venv, builds the UI, serves everything on http://127.0.0.1:8000
.\start.ps1 -Dev       # also starts the Vite dev server (hot reload) on http://localhost:5173
```

Or manually:

```powershell
cd backend
python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt
cd ..\frontend; npm install; npm run build; cd ..\backend
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

* UI: <http://127.0.0.1:8000> · API docs (Swagger): <http://127.0.0.1:8000/docs>
* All data lives in `local_data/` (`platform.db`, `nfs_source/`, `s3_bucket/`, `workflow_outputs/`, `logs/`) and survives restarts. Delete the contents of `local_data/` to start fresh. Override the location with `PLATFORM_DATA_DIR`.

## Try the acceptance flow (UI)

1. **Overview -> Simulate new sequencing run.** Creates `RUN_001` on the NFS share with three samples: `SAMPLE_001` (good), `SAMPLE_002` (poor read quality), `SAMPLE_003` (instrument warning).
2. The background sequencer (every 30 s by default; or press **Scan now**) discovers the run, copies files to S3, registers state and metadata, and runs the workflow.
3. **Workflow Executions** shows the 9-step timeline with logs. **Quality Control** shows the simulated InterOp/FastQC reports. `SAMPLE_001` = PASS, `SAMPLE_002` = FAIL.
4. **Downstream Applications**: only passing samples can be fetched; trying a failed one returns `403 QUALITY_GATE_BLOCKED` from the backend.
5. **Base Recall / Reruns -> SAMPLE_001 -> Update catalogue to V2.** The sample becomes `RERUN_REQUIRED` and is withdrawn from downstream immediately. Click **Start base recall**: the *same* sample gets a new attempt, the *same* S3 keys are overwritten, and the full attempt history is shown.
6. **NFS Explorer -> Verify source integrity**: NFS files are untouched by syncing (only the deliberately edited `catalogue.json` differs from its recorded checksum until re-synced).
7. Stop and restart the server: everything is still there.

Handy extras: *Simulate incomplete run* (no completion marker -> skipped), the catalogue form's "Simulated outcome" (flip FAIL<->PASS on rerun), **Settings** (scan interval, S3 versioning simulation, QC warning policy).

## NFS layout and the completion marker

```
local_data/nfs_source/RUN_001/
    RUN_COMPLETE                 <- marker; folders without it are skipped, never ingested
    SAMPLE_001/
        sample_metadata.json  catalogue.json  reads.fastq  instrument_data/
```

Once a run has the marker, its files are immutable through the API (uploads return 409). Drop your own runs in by hand: create the folders, add the files, write `RUN_COMPLETE` last, then scan.

## Key design decisions

* **State machine** `DISCOVERED -> INGESTING -> INGESTED -> PROCESSING -> QC_PENDING -> PASSED | FAILED`, plus `RERUN_REQUIRED`. All changes go through one validated `transition()`; attempts are claimed with an atomic conditional `UPDATE`, so a sample can never run twice concurrently.
* **A sample is `PASSED` only in `update_final_status`**, when QC passed *and* the catalogue version it processed is still the current one. Failed/interrupted jobs never touch `processed_version`.
* **Catalogue versions (V1, V2...) are tracked per sample and are unrelated to S3 versioning.** S3 reruns *overwrite* objects at the same keys. Native S3 versioning is an optional simulation, off by default (Settings).
* **No stale results**: changing the catalogue immediately sets `RERUN_REQUIRED`/quality `STALE`; a failed rerun leaves the sample `FAILED`; the gate also requires the latest accepted attempt to match the current catalogue version. Enforced in `services/downstream.py`, used by both fetch and download endpoints.
* **Reliability**: transient step errors are retried with backoff; each step is its own transaction; interrupted jobs are recovered on startup (attempt marked `INTERRUPTED`, a `RETRY` attempt queued); scans are serialised and per-run isolated.
* **Search index is derived data**: state changes write to it; nothing reads it to make decisions.
* Quality results come from simulators. Read count / length / GC are computed from the real FASTQ; per-base quality and adapter content come from a deterministic scenario model, so PASS/FAIL cases are reproducible. Scenario can be set per sample (`sample_metadata.json`) or overridden by the catalogue (`simulation_scenario`).
* Fault injection for testing: put `{"fault": {"step": "fastqc", "kind": "transient|permanent|crash", "times": 2}}` in `sample_metadata.json` (or the catalogue).

## API (see `/docs` for everything)

`GET/POST /api/runs`, `GET /api/runs/{id}`, `POST /api/sequencer/scan`, `GET /api/sequencer/status`, `GET /api/s3/objects`, `GET /api/metadata/search`, `GET /api/workflows`, `GET /api/workflows/{job_id}`, `POST /api/workflows/{run_id}/execute`, `POST /api/samples/{id}/catalogue/update`, `POST /api/samples/{id}/base-recall`, `GET /api/samples/{id}/history`, `GET /api/qc/results`, `GET /api/downstream/available`, `GET /api/downstream/{id}/fetch`.

## Tests

```powershell
cd backend
.\.venv\Scripts\python -m pytest
```

30 tests cover: folder discovery, duplicate detection, incomplete folders, initial ingestion, catalogue update, base-recall rerun, S3 overwrite, NFS-unchanged, FastQC PASS/FAIL, warning policy, downstream restriction (incl. guessed download URLs), stale-result protection, transient retry, permanent failure, crash recovery, path traversal, and state-machine / double-claim guards.

## Limitations

This is a simulation for learning and testing. It is single-machine, uses SQLite, and the "AWS Batch/miniWDL" engine is an in-process thread pool. InterOp and FastQC outputs are synthetic and must not be used for real scientific decisions.
