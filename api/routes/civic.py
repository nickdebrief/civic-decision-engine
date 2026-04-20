from __future__ import annotations

from fastapi import APIRouter, HTTPException
from api.models import CivicCaseRequest, CivicRunResponse

from civic_decision_engine_v10 import (
    format_civic_result,
    build_civic_run_metadata,
    save_run_snapshot,
    write_case_snapshot,
    append_engine_history,
)

router = APIRouter()


@router.post("/analyse", response_model=CivicRunResponse, tags=["Civic"])
def analyse(request: CivicCaseRequest) -> CivicRunResponse:
    case = request.model_dump()

    try:
        result = format_civic_result(case)
        metadata = build_civic_run_metadata(None, 1)

        output = {
            "run_metadata": metadata,
            "results": [result],
        }

        save_run_snapshot("civic", metadata["run_id"], output)
        write_case_snapshot(case)
        append_engine_history(case)

        return CivicRunResponse(**output)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
