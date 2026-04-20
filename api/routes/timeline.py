from __future__ import annotations

from fastapi import APIRouter, HTTPException
from api.models import TimelineRunResponse, CasesRequest

from civic_decision_engine_v10 import (
    load_stored_civic_runs,
    build_timeline_output_from_runs,
    save_run_snapshot,
    format_civic_result,
    build_civic_run_metadata,
)

router = APIRouter()


@router.get("/timeline", response_model=TimelineRunResponse, tags=["Analysis"])
def timeline_stored() -> TimelineRunResponse:
    try:
        stored_runs = load_stored_civic_runs()

        if not stored_runs:
            raise HTTPException(
                status_code=404,
                detail="No stored civic runs found in outputs/civic/",
            )

        output = build_timeline_output_from_runs(stored_runs)
        save_run_snapshot(
            "timeline",
            output["run_metadata"]["run_id"],
            output,
        )

        return TimelineRunResponse(**output)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/timeline", response_model=TimelineRunResponse, tags=["Analysis"])
def timeline_live(request: CasesRequest) -> TimelineRunResponse:
    if not request.cases:
        raise HTTPException(status_code=400, detail="No cases provided")

    try:
        runs = []
        for case_request in request.cases:
            case = case_request.model_dump()
            result = format_civic_result(case)
            metadata = build_civic_run_metadata(None, 1)
            runs.append(
                {
                    "run_metadata": metadata,
                    "results": [result],
                }
            )

        output = build_timeline_output_from_runs(runs)
        save_run_snapshot(
            "timeline",
            output["run_metadata"]["run_id"],
            output,
        )

        return TimelineRunResponse(**output)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
