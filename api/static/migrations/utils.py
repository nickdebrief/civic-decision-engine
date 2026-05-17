import hashlib
import json

def compute_verification_hash(
    reference: str,
    generated_at: str,
    finding: str,
    trajectory: str,
    conditions: list,
    system_state: str,
    generated_by: str = "Civic Decision Engine"
) -> str:
    canonical = {
        "reference": reference,
        "generated_at": generated_at,
        "finding": finding,
        "trajectory": trajectory,
        "conditions": sorted(conditions),  # sort for determinism
        "system_state": system_state,
        "generated_by": generated_by
    }
    payload = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()