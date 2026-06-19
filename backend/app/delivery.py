"""Per-booking deliverables: the unique video room, the natal chart and the
written report.

Isolated in its own module so both flows can build them with identical logic
and without circular imports:
* the client payment-claim endpoint (kept link-free), and
* the admin validation endpoint (which generates them, then emails the link).
"""
from __future__ import annotations

import json
import secrets

from .astrology import compute_chart
from .config import settings
from .models import Booking
from .report import build_report


def ensure_deliverables(booking: Booking) -> None:
    """Generate the video room, chart and report on the booking if missing.

    Idempotent: once a booking has a video link and a stored chart, calling this
    again is a no-op (so re-validating or resending never changes the room).
    """
    if booking.video_url and booking.chart_json:
        return

    room = booking.video_room or f"{settings.video_room_prefix}-{secrets.token_urlsafe(9)}"
    chart = compute_chart(
        booking.full_name, booking.birth_date, booking.birth_time, booking.birth_place
    )
    report = build_report(booking.full_name, booking.birth_date, chart)

    booking.video_room = room
    booking.video_url = f"{settings.video_base_url}/{room}"
    booking.chart_json = json.dumps(chart, ensure_ascii=False, default=str)
    booking.report_text = report
