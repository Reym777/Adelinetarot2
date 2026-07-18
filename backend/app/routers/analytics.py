from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..analytics import AnalyticsError, collect_events
from ..schemas import AnalyticsCollectRequest, AnalyticsCollectResponse
from ..security import write_rate_limit

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.post("/collect", response_model=AnalyticsCollectResponse)
def collect_analytics_event(
    payload: AnalyticsCollectRequest,
    _: None = Depends(write_rate_limit),
) -> AnalyticsCollectResponse:
    if payload.website:
        return AnalyticsCollectResponse(ok=True, message="Evento recibido.")

    events = [event.model_dump(exclude_none=True) for event in payload.events]
    try:
        ok, message = collect_events(
            client_id=payload.client_id,
            user_id=payload.user_id,
            events=events,
        )
    except AnalyticsError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return AnalyticsCollectResponse(ok=ok, message=message)