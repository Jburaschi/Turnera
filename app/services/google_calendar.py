from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_auth_httplib2 import AuthorizedHttp, Request as HttpRequest
import httplib2
from flask import current_app

from ..extensions import db
from ..timeutils import TZ_AR
from ..plans import GOOGLE_CALENDAR, plan_has, plan_is_usable
from ..models import GoogleCalendarConnection, Appointment


GOOGLE_TIMEOUT_SECONDS = 10

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
]


def company_has_google_plan(company) -> bool:
    """Google Calendar: incluido en PRO y PREMIUM, con el plan activo o en
    prueba vigente (la prueba incluye todas las funciones del plan)."""
    return plan_has(company, GOOGLE_CALENDAR) and plan_is_usable(company)


def get_google_oauth_config():
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None
    return {"client_id": client_id, "client_secret": client_secret}


def build_redirect_uri(request) -> str:
    """URL de retorno de OAuth. Es la misma para todos los negocios y es la
    que hay que registrar en Google Cloud (ver README)."""
    env = os.getenv("GOOGLE_REDIRECT_URI", "").strip()
    if env:
        return env
    return request.url_root.rstrip("/") + "/admin/integrations/google/callback"


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
        creds.refresh(HttpRequest(httplib2.Http(timeout=GOOGLE_TIMEOUT_SECONDS)))
        conn.access_token = creds.token
        conn.token_expiry = creds.expiry
        db.session.commit()
    # Timeout propio: sin esto, una demora de Google dejaba al cliente esperando
    # hasta 60 s (el mismo límite de gunicorn) y terminaba en error.
    http = AuthorizedHttp(creds, http=httplib2.Http(timeout=GOOGLE_TIMEOUT_SECONDS))
    return build("calendar", "v3", http=http, cache_discovery=False)


def _appointment_timezone(company) -> ZoneInfo:
    # La app funciona solo en Argentina: los turnos están en hora local AR.
    return TZ_AR


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

    body = {
        "summary": " · ".join(p for p in (service_name, who, employee_name) if p),
        "description": "\n".join(description_lines),
        "start": {"dateTime": start.isoformat(), "timeZone": tz.key},
        "end": {"dateTime": end.isoformat(), "timeZone": tz.key},
        # El profesional invitado aparece en su propio calendario (Gmail, Outlook…).
        # Lista vacía al actualizar = si cambió de profesional, se saca al anterior.
        "attendees": [],
    }
    employee = appointment.employee
    if employee:
        body["colorId"] = employee_color_id(employee)
        if employee.calendar_email:
            body["attendees"] = [{"email": employee.calendar_email, "displayName": employee.name}]
    return body


# Colores de evento de Google Calendar (1 a 11). Cada profesional tiene uno fijo.
GOOGLE_EVENT_COLORS = {
    '1': ('Lavanda', '#7986cb'), '2': ('Salvia', '#33b679'), '3': ('Uva', '#8e24aa'),
    '4': ('Flamenco', '#e67c73'), '5': ('Banana', '#f6bf26'), '6': ('Mandarina', '#f4511e'),
    '7': ('Pavo real', '#039be5'), '8': ('Grafito', '#616161'), '9': ('Arándano', '#3f51b5'),
    '10': ('Albahaca', '#0b8043'), '11': ('Tomate', '#d50000'),
}
_COLOR_ORDER = ['7', '2', '6', '3', '5', '11', '9', '10', '4', '1', '8']


def employee_color_id(employee) -> str:
    """Color fijo por profesional, según su orden dentro del negocio."""
    ids = sorted(e.id for e in employee.company.employees) if employee.company else [employee.id]
    pos = ids.index(employee.id) if employee.id in ids else employee.id
    return _COLOR_ORDER[pos % len(_COLOR_ORDER)]


def _send_updates(conn) -> str:
    """'all' manda el mail de Google a los invitados; 'none' solo lo agrega a su calendario."""
    return 'all' if getattr(conn, 'notify_staff', False) else 'none'


def ensure_google_event_for_appointment(appointment: Appointment) -> None:
    """Crea o actualiza el evento en Google Calendar. Nunca rompe el flujo:
    el turno ya está guardado; si Google falla, queda registrado en el log."""
    _safely(_ensure_google_event, appointment, "crear/actualizar")


def delete_google_event_for_appointment(appointment: Appointment) -> None:
    """Borra el evento de Google Calendar. Nunca rompe el flujo (ver arriba)."""
    _safely(_delete_google_event, appointment, "borrar")


def _safely(fn, appointment, action: str) -> None:
    try:
        fn(appointment)
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Google Calendar: no se pudo %s el evento del turno %s (empresa %s)",
            action, getattr(appointment, "id", "?"), getattr(appointment, "company_id", "?"),
        )


def _ensure_google_event(appointment: Appointment) -> None:
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
            .patch(calendarId=conn.calendar_id, eventId=appointment.google_event_id, body=body,
                   sendUpdates=_send_updates(conn))
            .execute()
        )
        appointment.google_event_id = updated.get("id") or appointment.google_event_id
        db.session.commit()
        return

    created = service.events().insert(calendarId=conn.calendar_id, body=body,
                                      sendUpdates=_send_updates(conn)).execute()
    appointment.google_event_id = created.get("id")
    db.session.commit()


def _delete_google_event(appointment: Appointment) -> None:
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
        service.events().delete(calendarId=conn.calendar_id, eventId=appointment.google_event_id,
                                sendUpdates=_send_updates(conn)).execute()
    except Exception:
        # Si ya no existe el evento, consideramos ok.
        pass
    appointment.google_event_id = None
    db.session.commit()

