from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from typing import Dict, Tuple
from zoneinfo import ZoneInfo

def _duration_minutes(service: str, notes: str) -> int:
    if service == "meditaciones":
        return 33
    if service == "tarot-terapeutico":
        m = re.search(r"Duracion:\s*(\d+)", notes or "", flags=re.IGNORECASE)
        if m:
            try:
                v = int(m.group(1))
                if v in (30, 45, 90):
                    return v
            except Exception:
                pass
        return 45
    if service == "paquete-magica":
        return 60
    return 45


def _resolve_tz() -> ZoneInfo:
    try:
        from .config import settings
        return ZoneInfo(settings.direct_schedule_timezone)
    except Exception:
        return ZoneInfo("UTC")


def _parse_start(intake_data: Dict[str, str]) -> Tuple[datetime, bool, str]:
    tz = _resolve_tz()
    d_raw = (intake_data.get("appointment_date") or "").strip()
    t_raw = (intake_data.get("appointment_time") or "").strip()

    def fallback(reason: str) -> Tuple[datetime, bool, str]:
        now = datetime.now(tz)
        slot = datetime.combine((now + timedelta(days=1)).date(), time(9, 0), tzinfo=tz)
        return slot, True, reason

    if not d_raw:
        return fallback("fecha ausente")

    if "T" in d_raw:
        left, right = d_raw.split("T", 1)
        d_raw = left.strip()
        if not t_raw and right:
            t_raw = right.strip()

    try:
        day = datetime.strptime(d_raw[:10], "%Y-%m-%d").date()
    except Exception:
        return fallback("fecha invalida")

    if t_raw:
        try:
            hh, mm = t_raw[:5].split(":", 1)
            return datetime.combine(day, time(hour=int(hh), minute=int(mm)), tzinfo=tz), False, ""
        except Exception:
            return datetime.combine(day, time(9, 0), tzinfo=tz), True, "hora invalida"

    return datetime.combine(day, time(9, 0), tzinfo=tz), True, "hora ausente"


def create_direct_appointment(intake_data: Dict[str, str]) -> Dict[str, str]:
    service = (intake_data.get("service") or "").strip()
    notes = intake_data.get("notes") or ""
    start_at, tentative, reason = _parse_start(intake_data)
    end_at = start_at + timedelta(minutes=_duration_minutes(service, notes))

    return {
        "start_at": start_at.isoformat(),
        "end_at": end_at.isoformat(),
        "video_room": "",
        "video_url": "",
        "tentative": "true" if tentative else "false",
        "reason": reason,
    }
