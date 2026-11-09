"""InterOp SIMULATOR. Deterministic per (sample, scenario); not real Illumina InterOp output."""
from typing import Any

from app.simulators import quality
from app.simulators.data_gen import rng_for

PROFILES = {
    "A_GOOD": dict(density=240.0, pf=92.0, q30=91.0, phasing=0.12, prephasing=0.08, error=0.40),
    "B_POOR_QUALITY": dict(density=235.0, pf=84.0, q30=74.0, phasing=0.21, prephasing=0.15, error=1.80),
    "C_INSTRUMENT_WARNING": dict(density=345.0, pf=66.0, q30=77.0, phasing=0.30, prephasing=0.22, error=1.10),
}


def generate_instrument_metrics(sample_id: str, scenario: str) -> dict[str, Any]:
    """Raw per-lane/tile style instrument metrics (the input to the InterOp summary)."""
    p = PROFILES[scenario]
    rng = rng_for("instrument", sample_id, scenario)
    lanes = []
    for lane in range(1, 5):
        lanes.append({
            "lane": lane,
            "tiles": 24,
            "cluster_density_k_mm2": round(p["density"] + rng.uniform(-6, 6), 1),
            "clusters_pf_pct": round(p["pf"] + rng.uniform(-1.2, 1.2), 2),
            "q30_pct": round(p["q30"] + rng.uniform(-1.0, 1.0), 2),
            "phasing_pct": round(p["phasing"] + rng.uniform(-0.02, 0.02), 3),
            "prephasing_pct": round(p["prephasing"] + rng.uniform(-0.02, 0.02), 3),
            "error_rate_pct": round(p["error"] + rng.uniform(-0.05, 0.05), 3),
        })
    return {"simulated": True, "source": "local instrument-metrics simulator", "lanes": lanes}


def simulate_interop(sample_id: str, scenario: str, instrument_metrics: dict[str, Any]) -> dict[str, Any]:
    lanes = instrument_metrics["lanes"]

    def avg(field: str) -> float:
        return round(sum(l[field] for l in lanes) / len(lanes), 2)

    metrics = {
        "cluster_density_k_mm2": avg("cluster_density_k_mm2"),
        "clusters_pf_pct": avg("clusters_pf_pct"),
        "q30_pct": avg("q30_pct"),
        "phasing_pct": avg("phasing_pct"),
        "prephasing_pct": avg("prephasing_pct"),
        "error_rate_pct": avg("error_rate_pct"),
    }
    checks = [
        {"metric": "cluster_density_k_mm2", "value": metrics["cluster_density_k_mm2"],
         "threshold": f"warn outside {quality.DENSITY_WARN}, fail outside {quality.DENSITY_FAIL}",
         "status": quality.outside_range(metrics["cluster_density_k_mm2"], quality.DENSITY_WARN, quality.DENSITY_FAIL)},
        {"metric": "clusters_pf_pct", "value": metrics["clusters_pf_pct"],
         "threshold": f"warn < {quality.PF_WARN}, fail < {quality.PF_FAIL}",
         "status": quality.low_is_bad(metrics["clusters_pf_pct"], quality.PF_WARN, quality.PF_FAIL)},
        {"metric": "q30_pct", "value": metrics["q30_pct"],
         "threshold": f"warn < {quality.Q30_WARN}, fail < {quality.Q30_FAIL}",
         "status": quality.low_is_bad(metrics["q30_pct"], quality.Q30_WARN, quality.Q30_FAIL)},
    ]
    return {
        "simulated": True,
        "tool": "InterOp (local simulation - not real Illumina InterOp output)",
        "sample_id": sample_id,
        "scenario": scenario,
        "metrics": metrics,
        "lanes": lanes,
        "checks": checks,
        "status": quality.worst([c["status"] for c in checks]),
    }
