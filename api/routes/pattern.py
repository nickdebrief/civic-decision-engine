from __future__ import annotations

from fastapi import APIRouter, HTTPException
from api.models import PatternRunResponse, CasesRequest

from civic_decision_engine_v10 import (
    load_stored_timeline_runs,
    build_pattern_output_from_timelines,
    build_timeline_output_from_runs,
    save_run_snapshot,
    format_civic_result,
    build_civic_run_metadata,
)

router = APIRouter()


@router.get("/pattern", response_model=PatternRunResponse, tags=["Analysis"])
def pattern_stored() -> PatternRunResponse:
    try:
        timeline_runs = load_stored_timeline_runs()

        if not timeline_runs:
            raise HTTPException(
                status_code=404,
                detail="No stored timeline runs found in outputs/timeline/",
            )

        output = build_pattern_output_from_timelines(timeline_runs)
        save_run_snapshot(
            "pattern",
            output["run_metadata"]["run_id"],
            output,
        )

        return PatternRunResponse(**output)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pattern", response_model=PatternRunResponse, tags=["Analysis"])
def pattern_live(request: CasesRequest) -> PatternRunResponse:
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

        timeline_output = build_timeline_output_from_runs(runs)
        timeline_runs = [timeline_output]

        output = build_pattern_output_from_timelines(timeline_runs)
        save_run_snapshot(
            "pattern",
            output["run_metadata"]["run_id"],
            output,
        )

        return PatternRunResponse(**output)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
