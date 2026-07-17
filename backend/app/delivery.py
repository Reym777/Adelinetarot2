"""Per-booking deliverables: the unique video room, the natal chart and the
written report.

Isolated in its own module so both flows can build them with identical logic
and without circular imports:
* the client payment-claim endpoint (kept link-free), and
* the admin validation endpoint (which generates them, then emails the link).
"""
from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .astrology import compute_chart
from .config import settings
from .google_calendar import upsert_direct_event
from .models import Booking
from .report import build_report


def ensure_deliverables(booking: Booking) -> None:
    """Generate Google Meet link, chart and report on the booking if missing.

    Idempotent: once a booking has a video link and a stored chart, calling this
    again is a no-op (so re-validating or resending keeps the same Meet event).
    """
    if booking.video_url and booking.chart_json and "meet.google.com" in str(booking.video_url):
        return

    chart = compute_chart(
        booking.full_name, booking.birth_date, booking.birth_time, booking.birth_place
    )
    report = build_report(booking.full_name, booking.birth_date, chart)

    try:
        tz = ZoneInfo(settings.direct_schedule_timezone)
    except Exception:
        tz = ZoneInfo("UTC")
    day = booking.appointment_date or (datetime.now(tz) + timedelta(days=1)).date()
    at = booking.appointment_time or time(9, 0)
    start_dt = datetime.combine(day, at, tzinfo=tz)
    end_dt = start_dt + timedelta(minutes=60)

    intake_data = {
        "service": "carta-astral",
        "first_name": booking.full_name,
        "last_name": "",
        "email": booking.email,
        "notes": f"Referencia: {booking.reference}",
    }
    appointment_data = {
        "start_at": start_dt.isoformat(),
        "end_at": end_dt.isoformat(),
        "video_url": booking.video_url or "",
        "video_room": booking.video_room or "",
    }
    ok, payload = upsert_direct_event(
        intake_data=intake_data,
        appointment_data=appointment_data,
        existing_event_id=booking.video_room or "",
        status="confirmed",
    )

    if ok:
        booking.video_room = str(payload.get("event_id") or booking.video_room or "")
        booking.video_url = str(
            payload.get("meet_url")
            or payload.get("html_link")
            or booking.video_url
            or ""
        )

    booking.chart_json = json.dumps(chart, ensure_ascii=False, default=str)
    booking.report_text = report
