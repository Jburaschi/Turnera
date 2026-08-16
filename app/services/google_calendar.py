from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

from ..extensions import db
from ..models import GoogleCalendarConnection, Appointment


GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
]


def company_has_google_plan(company) -> bool:
    plan = (company.plan_name or "").strip().upper()
    status = (company.plan_status or "").strip().upper()
    return status == "ACTIVE" and plan in {"PRO", "PREMIUM"}


def get_google_oauth_config():
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None
    return {"client_id": client_id, "client_secret": client_secret}


def build_redirect_uri(request, slug: str) -> str:
    env = os.getenv("GOOGLE_REDIRECT_URI", "").strip()
    if env:
        return env
    return request.url_root.rstrip("/") + f"/admin/{slug}/integrations/google/callback"


def _creds_from_connection(conn: GoogleCalendarConnection) -> Credentials:
    return Credentials(
        token=conn.access_token,
        refresh_token=conn.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("GOOGLE_CLIENT_ID", "").strip() or None,
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET", "").strip() or None,
        scopes=(conn.scopes.split() if conn.scopes else GOOGLE_SCOPES),
    )


def get_calendar_service(conn: GoogleCalendarConnection):
    creds = _creds_from_connection(conn)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        conn.access_token = creds.token
        conn.token_expiry = creds.expiry
        db.session.commit()
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _appointment_timezone(company) -> ZoneInfo:
    tz_name = (company.timezone or "America/Argentina/Buenos_Aires").strip()
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("America/Argentina/Buenos_Aires")


def _appointment_event_body(appointment: Appointment):
    company = appointment.company
    tz = _appointment_timezone(company)

    start = appointment.start_dt
    end = appointment.end_dt
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    if end.tzinfo is None:
        end = end.replace(tzinfo=tz)

    who = appointment.customer_display_name
    service_name = appointment.service.name if appointment.service else "Turno"
    employee_name = appointment.employee.name if appointment.employee else ""

    description_lines = [
        f"Cliente: {who}",
        f"Prestación: {service_name}",
    ]
    if employee_name:
        description_lines.append(f"Profesional: {employee_name}")
    if appointment.notes:
        description_lines.append(f"Notas: {appointment.notes}")

    return {
        "summary": f"{service_name} · {who}",
        "description": "\n".join(description_lines),
        "start": {"dateTime": start.isoformat(), "timeZone": tz.key},
        "end": {"dateTime": end.isoformat(), "timeZone": tz.key},
    }


def ensure_google_event_for_appointment(appointment: Appointment) -> None:
    company = appointment.company
    if not company_has_google_plan(company):
        return
    conn = company.google_calendar
    if not conn or not conn.enabled or not conn.refresh_token:
        return
    if appointment.status != "BOOKED":
        return

    service = get_calendar_service(conn)
    body = _appointment_event_body(appointment)

    if appointment.google_event_id:
        updated = (
            service.events()
            .patch(calendarId=conn.calendar_id, eventId=appointment.google_event_id, body=body)
            .execute()
        )
        appointment.google_event_id = updated.get("id") or appointment.google_event_id
        db.session.commit()
        return

    created = service.events().insert(calendarId=conn.calendar_id, body=body).execute()
    appointment.google_event_id = created.get("id")
    db.session.commit()


def delete_google_event_for_appointment(appointment: Appointment) -> None:
    company = appointment.company
    if not company_has_google_plan(company):
        return
    conn = company.google_calendar
    if not conn or not conn.enabled or not conn.refresh_token:
        return
    if not appointment.google_event_id:
        return

    service = get_calendar_service(conn)
    try:
        service.events().delete(calendarId=conn.calendar_id, eventId=appointment.google_event_id).execute()
    except Exception:
        # Si ya no existe el evento, consideramos ok.
        pass
    appointment.google_event_id = None
    db.session.commit()

