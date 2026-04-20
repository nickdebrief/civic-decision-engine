from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from api.models import CasesRequest, AdaptationRunResponse

from civic_decision_engine_v10 import (
    extract_behaviour_summary,
    save_run_snapshot,
)

router = APIRouter()


def interpret_adaptation_result(
    labels: list[str],
    indices: list[int],
    trajectory: str,
    moment_of_change: dict[str, str | int] | None,
) -> str:
    if not labels or not indices:
        return "No behavioural sequence was available for adaptation analysis."

    if trajectory == "Stable" and moment_of_change is None:
        return "Behaviour remained stable across compared cases with no detected moment of change."

    if trajectory == "Deteriorating" and moment_of_change is not None:
        return (
            f"Behaviour shows increasing institutional resistance or containment over time, "
            f"with a shift from {moment_of_change['from']} to {moment_of_change['to']} "
            f"at run {moment_of_change['at_index']}."
        )

    if trajectory == "Improving" and moment_of_change is not None:
        return (
            f"Behaviour shows improving engagement over time, with a shift from "
            f"{moment_of_change['from']} to {moment_of_change['to']} "
            f"at run {moment_of_change['at_index']}."
        )

    if trajectory == "Mixed" and moment_of_change is not None:
        return (
            f"Behaviour changes across compared cases, with the first detected shift from "
            f"{moment_of_change['from']} to {moment_of_change['to']} "
            f"at run {moment_of_change['at_index']}."
        )

    return "Behaviour varies across compared cases without a single clear directional pattern."


@router.post("/adaptation", response_model=AdaptationRunResponse, tags=["Civic"])
def adaptation(request: CasesRequest) -> AdaptationRunResponse:
    if not request.cases:
        raise HTTPException(status_code=400, detail="No cases provided")

    cases = [r.model_dump() for r in request.cases]

    try:
        summaries = [extract_behaviour_summary(c) for c in cases]

        labels = [s["label"] for s in summaries]
        indices = [s["index"] for s in summaries]
        case_sequence = [s["case"] for s in summaries]

        if len(set(indices)) == 1:
            trajectory = "Stable"
        elif indices == sorted(indices):
            trajectory = "Deteriorating"
        elif indices == sorted(indices, reverse=True):
            trajectory = "Improving"
        else:
            trajectory = "Mixed"

        moment_of_change = None
        for i in range(1, len(labels)):
            if labels[i] != labels[i - 1]:
                moment_of_change = {
                    "from": labels[i - 1],
                    "to": labels[i],
                    "at_index": i + 1,
                }
                break

        interpretation = interpret_adaptation_result(
            labels,
            indices,
            trajectory,
            moment_of_change,
        )

        now = datetime.now(timezone.utc)
        run_id = f"compare-analysis-{now.strftime('%Y-%m-%d-%H%M%S')}"

        output = {
            "run_metadata": {
                "run_id": run_id,
                "generated_at": now.isoformat(),
                "mode": "compare_analysis",
                "case_count": len(cases),
                "lineage": {"version": "v10"},
            },
            "results": [
                {
                    "case_sequence": case_sequence,
                    "behaviour_indices": indices,
                    "progression": labels,
                    "trajectory": trajectory,
                    "moment_of_change": moment_of_change,
                    "interpretation": interpretation,
                }
            ],
        }

        save_run_snapshot("compare", run_id, output)
        return AdaptationRunResponse(**output)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
