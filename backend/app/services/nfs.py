"""NFS simulator: a local folder tree.

Layout::

    nfs_source/RUN_001/
        RUN_COMPLETE            <- completion marker; folders without it are never ingested
        SAMPLE_001/
            sample_metadata.json
            catalogue.json
            reads.fastq
            instrument_data/

The platform only ever READS from here. The sole writer besides test-data creation is
``write_catalogue`` (a scientist editing catalogue information at the source).
"""
import json
import re
from pathlib import Path
from typing import Any, Optional

from app.config import get_config
from app.simulators.data_gen import SCENARIOS, generate_sample_folder
from app.utils.common import ID_RE, atomic_write_bytes, atomic_write_json, safe_join, sha256_file

MARKER = "RUN_COMPLETE"
REQUIRED_FILES = ("sample_metadata.json", "catalogue.json", "reads.fastq")
_SAMPLE_NUM = re.compile(r"^SAMPLE_(\d+)$")
_RUN_NUM = re.compile(r"^RUN_(\d+)$")


class NfsError(Exception):
    pass


def nfs_root() -> Path:
    return get_config().nfs_dir


def run_dir(run_id: str) -> Path:
    if not ID_RE.match(run_id):
        raise NfsError(f"invalid run id: {run_id!r}")
    return nfs_root() / run_id


def sample_dir(run_id: str, sample_id: str) -> Path:
    if not ID_RE.match(sample_id):
        raise NfsError(f"invalid sample id: {sample_id!r}")
    return run_dir(run_id) / sample_id


def is_complete(run_id: str) -> bool:
    return (run_dir(run_id) / MARKER).is_file()


def list_run_ids() -> list[str]:
    root = nfs_root()
    return sorted(p.name for p in root.iterdir() if p.is_dir() and ID_RE.match(p.name)) if root.exists() else []


def list_sample_ids(run_id: str) -> list[str]:
    rd = run_dir(run_id)
    if not rd.is_dir():
        return []
    return sorted(p.name for p in rd.iterdir() if p.is_dir() and ID_RE.match(p.name))


def next_run_id(known: list[str] = ()) -> str:
    nums = [int(m.group(1)) for r in [*list_run_ids(), *known] if (m := _RUN_NUM.match(r))]
    return f"RUN_{(max(nums) + 1) if nums else 1:03d}"


def next_sample_numbers(count: int, known: list[str] = ()) -> list[str]:
    nums = [int(m.group(1)) for r in list_run_ids() for s in list_sample_ids(r) if (m := _SAMPLE_NUM.match(s))]
    nums += [int(m.group(1)) for s in known if (m := _SAMPLE_NUM.match(s))]
    start = (max(nums) if nums else 0) + 1
    return [f"SAMPLE_{n:03d}" for n in range(start, start + count)]


# ---- creation (simulating instruments / scientists dropping data on the share) ----
def create_run(run_id: Optional[str], sample_count: int, scenarios: Optional[list[str]] = None,
               mark_complete: bool = True, known_runs: list[str] = (), known_samples: list[str] = (),
               catalogue_version: str = "V1") -> dict[str, Any]:
    run_id = run_id or next_run_id(known_runs)
    rd = run_dir(run_id)
    if rd.exists():
        raise NfsError(f"run folder already exists: {run_id}")
    rd.mkdir(parents=True)
    created = []
    for i, sid in enumerate(next_sample_numbers(sample_count, known_samples)):
        scenario = (scenarios[i] if scenarios and i < len(scenarios) else SCENARIOS[i % len(SCENARIOS)])
        add_sample(run_id, sid, scenario, catalogue_version=catalogue_version, _allow_complete=True)
        created.append(sid)
    if mark_complete:
        mark_run_complete(run_id)
    return {"run_id": run_id, "samples": created, "complete": mark_complete}


def add_sample(run_id: str, sample_id: Optional[str], scenario: str = "A_GOOD", catalogue_version: str = "V1",
               extra_metadata: Optional[dict] = None, known_samples: list[str] = (),
               _allow_complete: bool = False) -> str:
    if scenario not in SCENARIOS:
        raise NfsError(f"unknown scenario {scenario!r}; expected one of {SCENARIOS}")
    rd = run_dir(run_id)
    if not rd.is_dir():
        raise NfsError(f"run folder not found: {run_id}")
    if is_complete(run_id) and not _allow_complete:
        raise NfsError("run is marked complete; its NFS contents are immutable")
    sample_id = sample_id or next_sample_numbers(1, known_samples)[0]
    sd = sample_dir(run_id, sample_id)
    if sd.exists():
        raise NfsError(f"sample folder already exists: {sample_id}")
    generate_sample_folder(sd, run_id, sample_id, scenario, catalogue_version, extra_metadata)
    return sample_id


def upload_file(run_id: str, sample_id: str, rel_path: str, data: bytes) -> Path:
    if is_complete(run_id):
        raise NfsError("run is marked complete; its NFS contents are immutable")
    sd = sample_dir(run_id, sample_id)
    sd.mkdir(parents=True, exist_ok=True)
    try:
        target = safe_join(sd, rel_path)
    except ValueError as e:
        raise NfsError(str(e)) from e
    if target == sd.resolve():
        raise NfsError("file path required")
    atomic_write_bytes(target, data)
    return target


def mark_run_complete(run_id: str) -> None:
    rd = run_dir(run_id)
    if not rd.is_dir():
        raise NfsError(f"run folder not found: {run_id}")
    atomic_write_json(rd / MARKER, {"complete": True, "samples": list_sample_ids(run_id)})


# ---- reading ----
def read_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise NfsError(f"{path.name} must contain a JSON object")
    return data


def read_catalogue(run_id: str, sample_id: str) -> dict[str, Any]:
    return read_json(sample_dir(run_id, sample_id) / "catalogue.json")


def read_metadata(run_id: str, sample_id: str) -> dict[str, Any]:
    return read_json(sample_dir(run_id, sample_id) / "sample_metadata.json")


def write_catalogue(run_id: str, sample_id: str, content: dict[str, Any]) -> None:
    """A scientist updating catalogue information at the source."""
    atomic_write_json(sample_dir(run_id, sample_id) / "catalogue.json", content)


def iter_files(sd: Path) -> list[Path]:
    return sorted(p for p in sd.rglob("*") if p.is_file() and not p.name.startswith(".tmp-"))


def fingerprint(sd: Path) -> dict[str, str]:
    """relative path -> sha256 for every file under a sample folder."""
    return {p.relative_to(sd).as_posix(): sha256_file(p) for p in iter_files(sd)}


def validate_sample_dir(run_id: str, sample_id: str) -> list[str]:
    """Source-folder readiness check. Returns a list of problems (empty == ready)."""
    problems: list[str] = []
    if not is_complete(run_id):
        problems.append(f"run {run_id} has no {MARKER} marker")
    sd = sample_dir(run_id, sample_id)
    if not sd.is_dir():
        return [*problems, f"sample folder missing: {sample_id}"]
    for name in REQUIRED_FILES:
        if not (sd / name).is_file():
            problems.append(f"missing required file: {name}")
    if problems:
        return problems
    for name in ("sample_metadata.json", "catalogue.json"):
        try:
            read_json(sd / name)
        except (ValueError, NfsError) as e:
            problems.append(f"{name} is not valid JSON object: {e}")
    try:
        if not str(read_json(sd / "catalogue.json").get("version", "")).strip():
            problems.append("catalogue.json has no 'version'")
    except (ValueError, NfsError):
        pass
    lines = (sd / "reads.fastq").read_text(encoding="ascii", errors="replace").splitlines()
    if not lines:
        problems.append("reads.fastq is empty")
    elif len(lines) % 4 != 0 or not lines[0].startswith("@") or not lines[2].startswith("+"):
        problems.append("reads.fastq is not valid FASTQ (4-line records)")
    return problems


def tree() -> list[dict[str, Any]]:
    """Explorer view of everything on the share (including not-yet-complete runs)."""
    out = []
    for rid in list_run_ids():
        samples = []
        for sid in list_sample_ids(rid):
            sd = sample_dir(rid, sid)
            samples.append({"sample_id": sid, "files": [
                {"path": p.relative_to(sd).as_posix(), "size": p.stat().st_size} for p in iter_files(sd)]})
        out.append({"run_id": rid, "complete": is_complete(rid), "samples": samples})
    return out
