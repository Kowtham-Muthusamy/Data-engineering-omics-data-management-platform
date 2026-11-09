"""Quality thresholds and the quality gate decision (shared by the simulators and the workflow)."""
from typing import Any

# InterOp-style instrument thresholds (SIMULATED values, not Illumina's real acceptance criteria)
Q30_WARN, Q30_FAIL = 80.0, 70.0
PF_WARN, PF_FAIL = 70.0, 60.0
DENSITY_WARN = (150.0, 320.0)   # K clusters / mm2
DENSITY_FAIL = (100.0, 400.0)

# FastQC-style thresholds
BASE_QUAL_WARN, BASE_QUAL_FAIL = 28.0, 20.0         # lowest per-position median
SEQ_QUAL_WARN, SEQ_QUAL_FAIL = 27.0, 20.0           # mode of mean read quality
ADAPTER_WARN, ADAPTER_FAIL = 5.0, 10.0              # % reads with adapter at the end


def worst(statuses: list[str]) -> str:
    return "FAIL" if "FAIL" in statuses else "WARN" if "WARN" in statuses else "PASS"


def low_is_bad(value: float, warn: float, fail: float) -> str:
    return "FAIL" if value < fail else "WARN" if value < warn else "PASS"


def high_is_bad(value: float, warn: float, fail: float) -> str:
    return "FAIL" if value >= fail else "WARN" if value >= warn else "PASS"


def outside_range(value: float, warn: tuple[float, float], fail: tuple[float, float]) -> str:
    if value < fail[0] or value > fail[1]:
        return "FAIL"
    return "WARN" if value < warn[0] or value > warn[1] else "PASS"


def evaluate(interop: dict[str, Any], fastqc: dict[str, Any], warning_policy: str = "PASS") -> dict[str, Any]:
    """The quality gate. FAIL anywhere -> FAIL. WARN anywhere -> decided by ``warning_policy``."""
    reasons: list[str] = []
    for check in interop["checks"]:
        if check["status"] != "PASS":
            reasons.append(f"InterOp {check['metric']}={check['value']} -> {check['status']}")
    for name, module in fastqc["modules"].items():
        if module["status"] != "PASS":
            reasons.append(f"FastQC {name} -> {module['status']}")
    overall_inputs = [interop["status"], fastqc["status"]]
    if "FAIL" in overall_inputs:
        overall = "FAIL"
    elif "WARN" in overall_inputs:
        overall = "PASS" if warning_policy.upper() == "PASS" else "FAIL"
        reasons.append(f"warnings treated as {overall} (warning_policy={warning_policy.upper()})")
    else:
        overall = "PASS"
        reasons.append("all InterOp and FastQC checks passed")
    return {"overall": overall, "reasons": reasons}
