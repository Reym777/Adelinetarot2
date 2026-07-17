from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from functools import lru_cache
from typing import Dict, Tuple

from .config import settings

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
except Exception:  # pragma: no cover - optional dependency
    service_account = None  # type: ignore[assignment]
    build = None  # type: ignore[assignment]

_CAL_SCOPE = ["https://www.googleapis.com/auth/calendar"]
_ALLOWED_STATUS = {"tentative", "confirmed", "cancelled"}


def _is_service_account_attendee_forbidden(exc: Exception) -> bool:
    txt = str(exc or "").lower()
    return (
        "forbiddenforserviceaccounts" in txt
        or "service accounts cannot invite attendees" in txt
    )


def _normalize_status(status: str) -> str:
    value = str(status or "").strip().lower()
    if value in _ALLOWED_STATUS:
        return value
    default_status = str(settings.google_calendar_default_status or "tentative").strip().lower()
    if default_status in _ALLOWED_STATUS:
        return default_status
    return "tentative"


def _credentials_payload() -> Dict:
    raw = (settings.google_calendar_credentials_json or "").strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        try:
            return json.loads(raw)
        except Exception:
            return {}

    # Treat as file path (absolute or relative to backend cwd).
    try:
        if os.path.exists(raw):
            with open(raw, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        return {}
    return {}


def _attendee_invites_allowed() -> bool:
    payload = _credentials_payload()
    if not payload:
        return False
    if str(payload.get("type") or "").strip() != "service_account":
        return True
    return bool(str(settings.google_calendar_delegate_user or "").strip())


def enabled() -> bool:
    return bool(settings.google_calendar_enabled and settings.google_calendar_credentials_json)


def _send_updates_value() -> str:
    # Business requirement: always email Google Calendar invitations/updates.
    return "all"


@lru_cache(maxsize=1)
def _calendar_service():
    if not enabled() or service_account is None or build is None:
        return None

    payload = _credentials_payload()
    if not payload:
        return None

    creds = service_account.Credentials.from_service_account_info(payload, scopes=_CAL_SCOPE)
    delegated_user = str(settings.google_calendar_delegate_user or "").strip()
    if delegated_user:
        creds = creds.with_subject(delegated_user)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _build_event_payload(
    intake_data: Dict[str, str],
    appointment_data: Dict[str, str],
    status: str,
    create_conference: bool,
    include_attendees: bool,
) -> Dict:
    first_name = (intake_data.get("first_name") or "").strip()
    last_name = (intake_data.get("last_name") or "").strip()
    service = (intake_data.get("service") or "").strip()
    email = (intake_data.get("email") or "").strip()
    payer_email = (intake_data.get("payer_email") or "").strip()
    notes = (intake_data.get("notes") or "").strip()
    start_raw = (appointment_data.get("start_at") or intake_data.get("appointment_start_at") or "").strip()
    end_raw = (appointment_data.get("end_at") or intake_data.get("appointment_end_at") or "").strip()
    if not start_raw:
        return {}

    summary = f"{service} - {first_name} {last_name}".strip()
    attendees = []
    seen_attendees = set()
    for addr in (email, payer_email):
        key = str(addr or "").strip().lower()
        if key and key not in seen_attendees:
            attendees.append({"email": key})
            seen_attendees.add(key)
    business_email = (settings.notify_recipient or "").strip()
    business_key = business_email.lower()
    if business_key and business_key not in seen_attendees:
        attendees.append({"email": business_email})
        seen_attendees.add(business_key)

    description_lines = [
        f"Servicio: {service}",
        f"Cliente: {first_name} {last_name}".strip(),
        f"Email: {email}" if email else "",
        f"Email pagador: {payer_email}" if payer_email else "",
        "Videollamada: Google Meet",
        "",
        "Notas del formulario:",
        notes,
    ]
    description = "\n".join([line for line in description_lines if line is not None])

    payload: Dict = {
        "summary": summary or "Cita Adelinemagica",
        "description": description,
        "status": _normalize_status(status),
        "start": {"dateTime": start_raw},
        "end": {"dateTime": end_raw or start_raw},
    }
    if include_attendees and attendees:
        payload["attendees"] = attendees
    if create_conference:
        payload["conferenceData"] = {
            "createRequest": {
                "requestId": f"adm-{secrets.token_urlsafe(12)}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }
    return payload


def upsert_direct_event(
    intake_data: Dict[str, str],
    appointment_data: Dict[str, str],
    existing_event_id: str = "",
    status: str = "tentative",
) -> Tuple[bool, Dict[str, str]]:
    if not enabled():
        return False, {"error": "google_calendar_disabled"}

    service = _calendar_service()
    if service is None:
        return False, {"error": "google_calendar_unavailable"}

    current_video_url = str(appointment_data.get("video_url") or "").strip().lower()
    has_meet_link = "meet.google.com" in current_video_url
    allow_attendees = _attendee_invites_allowed()
    payload = _build_event_payload(
        intake_data,
        appointment_data,
        status,
        create_conference=(not bool(existing_event_id)) or (not has_meet_link),
        include_attendees=allow_attendees,
    )
    if not payload:
        return False, {"error": "appointment_start_missing"}

    try:
        if existing_event_id:
            try:
                event = (
                    service.events()
                    .patch(
                        calendarId=settings.google_calendar_id,
                        eventId=existing_event_id,
                        body=payload,
                        sendUpdates=_send_updates_value(),
                        conferenceDataVersion=1,
                    )
                    .execute()
                )
            except Exception:
                # Stale/non-Google event id (legacy room id): recreate cleanly.
                event = (
                    service.events()
                    .insert(
                        calendarId=settings.google_calendar_id,
                        body=payload,
                        sendUpdates=_send_updates_value(),
                        conferenceDataVersion=1,
                    )
                    .execute()
                )
        else:
            event = (
                service.events()
                .insert(
                    calendarId=settings.google_calendar_id,
                    body=payload,
                    sendUpdates=_send_updates_value(),
                    conferenceDataVersion=1,
                )
                .execute()
            )
    except Exception as exc:
        if _is_service_account_attendee_forbidden(exc) and payload.get("attendees"):
            payload_no_attendees = dict(payload)
            payload_no_attendees.pop("attendees", None)
            try:
                if existing_event_id:
                    event = (
                        service.events()
                        .patch(
                            calendarId=settings.google_calendar_id,
                            eventId=existing_event_id,
                            body=payload_no_attendees,
                            sendUpdates="none",
                            conferenceDataVersion=1,
                        )
                        .execute()
                    )
                else:
                    event = (
                        service.events()
                        .insert(
                            calendarId=settings.google_calendar_id,
                            body=payload_no_attendees,
                            sendUpdates="none",
                            conferenceDataVersion=1,
                        )
                        .execute()
                    )
            except Exception as exc_retry:
                return False, {"error": str(exc_retry)}

            conference = event.get("conferenceData") or {}
            entry_points = conference.get("entryPoints") or []
            meet_url = str(event.get("hangoutLink") or "").strip()
            if not meet_url:
                for ep in entry_points:
                    if str(ep.get("entryPointType") or "") == "video" and ep.get("uri"):
                        meet_url = str(ep.get("uri") or "").strip()
                        if meet_url:
                            break

            return True, {
                "event_id": str(event.get("id") or ""),
                "event_status": str(event.get("status") or _normalize_status(status)),
                "html_link": str(event.get("htmlLink") or ""),
                "meet_url": meet_url,
                "warning": "attendees_forbidden_for_service_account",
                "synced_at": datetime.now(timezone.utc).isoformat(),
            }

        return False, {"error": str(exc)}

    conference = event.get("conferenceData") or {}
    entry_points = conference.get("entryPoints") or []
    meet_url = str(event.get("hangoutLink") or "").strip()
    if not meet_url:
        for ep in entry_points:
            if str(ep.get("entryPointType") or "") == "video" and ep.get("uri"):
                meet_url = str(ep.get("uri") or "").strip()
                if meet_url:
                    break

    return True, {
        "event_id": str(event.get("id") or ""),
        "event_status": str(event.get("status") or _normalize_status(status)),
        "html_link": str(event.get("htmlLink") or ""),
        "meet_url": meet_url,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
