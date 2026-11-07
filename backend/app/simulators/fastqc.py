"""FastQC SIMULATOR. Not the real FastQC.

Read count, length distribution and GC content are computed from the actual FASTQ file.
Per-base quality and adapter content come from a deterministic scenario model, so PASS / FAIL
cases are reproducible and a catalogue change can legitimately change the outcome of a rerun.
"""
from collections import Counter
from pathlib import Path
from typing import Any

from app.simulators import quality
from app.simulators.data_gen import rng_for

# (median Q at first base, median Q at last base, mean read Q, adapter % at read end)
PROFILES = {
    "A_GOOD": (36.0, 33.0, 34.0, 0.6),
    "B_POOR_QUALITY": (33.0, 12.0, 22.0, 11.0),
    "C_INSTRUMENT_WARNING": (36.0, 33.0, 34.0, 0.8),
}


def _read_fastq_stats(path: Path) -> tuple[int, Counter, float]:
    lengths: Counter = Counter()
    gc = bases = reads = 0
    with open(path, "r", encoding="ascii", errors="replace") as f:
        for i, line in enumerate(f):
            if i % 4 == 1:
                seq = line.strip().upper()
                reads += 1
                lengths[len(seq)] += 1
                gc += seq.count("G") + seq.count("C")
                bases += len(seq)
    return reads, lengths, (100.0 * gc / bases if bases else 0.0)


def simulate_fastqc(sample_id: str, scenario: str, fastq_path: Path) -> dict[str, Any]:
    reads, lengths, gc_pct = _read_fastq_stats(fastq_path)
    if reads == 0:
        raise ValueError("FASTQ contains no reads")
    max_len = max(lengths)
    q_start, q_end, q_mean, adapter_end = PROFILES[scenario]
    rng = rng_for("fastqc", sample_id, scenario)

    per_base = []
    for pos in range(1, max_len + 1):
        frac = (pos - 1) / max(1, max_len - 1)
        median = q_start + (q_end - q_start) * frac + rng.uniform(-0.6, 0.6)
        per_base.append({"position": pos, "median": round(median, 2),
                         "lower_quartile": round(median - 2.5 - 2 * frac, 2),
                         "upper_quartile": round(min(41.0, median + 2.0), 2)})
    worst_median = min(p["median"] for p in per_base)

    adapter_curve = [{"position": p["position"],
                      "adapter_pct": round(adapter_end * (max(0, p["position"] - max_len * 0.7) / (max_len * 0.3)), 2)}
                     for p in per_base]
    adapter_final = adapter_curve[-1]["adapter_pct"]
    length_set = sorted(lengths)

    modules = {
        "per_base_sequence_quality": {"status": quality.low_is_bad(worst_median, quality.BASE_QUAL_WARN, quality.BASE_QUAL_FAIL),
                                      "lowest_median_quality": round(worst_median, 2)},
        "per_sequence_quality_scores": {"status": quality.low_is_bad(q_mean, quality.SEQ_QUAL_WARN, quality.SEQ_QUAL_FAIL),
                                        "mean_read_quality": q_mean},
        "per_sequence_gc_content": {"status": "PASS" if 35 <= gc_pct <= 65 else "WARN", "mean_gc_pct": round(gc_pct, 2)},
        "sequence_length_distribution": {"status": "PASS" if len(length_set) == 1 else "WARN",
                                         "lengths": {str(k): v for k, v in sorted(lengths.items())}},
        "adapter_content": {"status": quality.high_is_bad(adapter_final, quality.ADAPTER_WARN, quality.ADAPTER_FAIL),
                            "max_adapter_pct": adapter_final},
    }
    return {
        "simulated": True,
        "tool": "FastQC (local simulation - not real FastQC output)",
        "sample_id": sample_id,
        "scenario": scenario,
        "basic_statistics": {"total_reads": reads, "sequence_length": f"{length_set[0]}-{length_set[-1]}",
                             "gc_pct": round(gc_pct, 2)},
        "per_base_quality": per_base,
        "adapter_content_curve": adapter_curve,
        "modules": modules,
        "status": quality.worst([m["status"] for m in modules.values()]),
    }
