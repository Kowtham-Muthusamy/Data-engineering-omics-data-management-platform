"""Deterministic dummy sequencing data (SIMULATED - not real instrument output)."""
import hashlib
import random
from pathlib import Path

from app.utils.common import atomic_write_bytes, atomic_write_json

ADAPTER = "AGATCGGAAGAGC"
SCENARIOS = ("A_GOOD", "B_POOR_QUALITY", "C_INSTRUMENT_WARNING")
SCENARIO_LABELS = {
    "A_GOOD": "Good quality sample (PASS)",
    "B_POOR_QUALITY": "Poor read quality (FAIL)",
    "C_INSTRUMENT_WARNING": "Instrument quality warning (configurable)",
}
ORGANISMS = ("Homo sapiens", "Mus musculus", "Escherichia coli", "Arabidopsis thaliana")


def rng_for(*parts: object) -> random.Random:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def generate_fastq(path: Path, sample_id: str, scenario: str, n_reads: int = 200, read_len: int = 100) -> None:
    rng = rng_for("fastq", sample_id, scenario)
    poor = scenario == "B_POOR_QUALITY"
    adapter_rate = 0.12 if poor else 0.01
    out: list[str] = []
    for i in range(n_reads):
        seq = [rng.choice("ACGT") for _ in range(read_len)]
        if rng.random() < adapter_rate:
            start = read_len - len(ADAPTER) - rng.randint(0, 10)
            seq[start:start + len(ADAPTER)] = ADAPTER
        quals = []
        for pos in range(read_len):
            frac = pos / (read_len - 1)
            base = 33 - 20 * frac if poor else 37 - 3 * frac
            q = max(2, min(41, int(rng.gauss(base, 2.5))))
            quals.append(chr(33 + q))
        out += [f"@{sample_id}_{i + 1:05d} 1:N:0:ATCACG", "".join(seq), "+", "".join(quals)]
    atomic_write_bytes(path, ("\n".join(out) + "\n").encode("ascii"))


def generate_sample_folder(sample_dir: Path, run_id: str, sample_id: str, scenario: str,
                           catalogue_version: str = "V1", extra_metadata: dict | None = None) -> None:
    rng = rng_for("meta", sample_id)
    sample_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "sample_id": sample_id,
        "run_id": run_id,
        "organism": ORGANISMS[rng.randrange(len(ORGANISMS))],
        "library_prep": rng.choice(["TruSeq DNA PCR-Free", "Nextera Flex", "TruSeq Stranded mRNA"]),
        "instrument": "SIMULATED-SEQ-01",
        "flowcell": f"FC{rng.randint(10000, 99999)}",
        "lane": rng.randint(1, 4),
        "scenario": scenario,
        "scenario_description": SCENARIO_LABELS[scenario],
        "simulated": True,
    }
    metadata.update(extra_metadata or {})
    atomic_write_json(sample_dir / "sample_metadata.json", metadata)
    atomic_write_json(sample_dir / "catalogue.json", {
        "version": catalogue_version,
        "sample_id": sample_id,
        "reference_genome": "GRCh38" if metadata["organism"] == "Homo sapiens" else "reference-v1",
        "base_calling_profile": "default",
        "notes": "initial catalogue entry",
    })
    generate_fastq(sample_dir / "reads.fastq", sample_id, scenario)
    inst = sample_dir / "instrument_data"
    atomic_write_json(inst / "run_parameters.json", {
        "run_id": run_id, "instrument": metadata["instrument"], "flowcell": metadata["flowcell"],
        "read_length": 100, "cycles": 100, "simulated": True,
    })
    atomic_write_bytes(inst / "InterOp_Summary.bin", bytes(rng.randrange(256) for _ in range(512)))
