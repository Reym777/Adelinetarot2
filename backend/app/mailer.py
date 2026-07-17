"""Transactional email (SMTP) used to deliver the private video-call link.

Design / security notes:
* The link to the video call is delivered ONLY by email, and only after
  Adelinemagica has confirmed she received the payment (admin validation).
* SMTP credentials come exclusively from the environment (see ``config.py``);
  nothing is hardcoded.
* The recipient address is an ``EmailStr`` validated at booking time and the
  display name is sanitised (no ``<>@``), which prevents header injection.
* Sending failures are reported back to the caller (and surfaced in the admin
  panel) instead of raising, so validating a payment never 500s on a mail glitch.
"""
from __future__ import annotations

import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
import json
from datetime import datetime, timezone
from typing import Tuple
from urllib import error as urlerror
from urllib import request as urlrequest

from .config import settings
from .models import Booking

logger = logging.getLogger("adelinemagica.mailer")


def send_article_copy_to_contact(
    *,
    title: str,
    content_html: str,
    slug: str = "",
) -> Tuple[bool, str]:
    """Send full article content to contact@adelinemagica.com from admin panel."""
    if not (settings.resend_enabled or settings.mail_enabled):
        return False, "Correo no configurado"

    clean_title = str(title or "").strip() or "Articulo sin titulo"
    clean_slug = str(slug or "").strip()
    html = str(content_html or "").strip() or "<p>(sin contenido)</p>"
    plain = re.sub(r"<[^>]+>", " ", html)
    plain = re.sub(r"\s+", " ", plain).strip() or "(sin contenido)"

    msg = EmailMessage()
    msg["Subject"] = f"[{settings.business_name}] Guardar en mail: {clean_title}"
    msg["From"] = settings.effective_sender or settings.resend_from
    msg["To"] = "contact@adelinemagica.com"
    if settings.mail_reply_to:
        msg["Reply-To"] = settings.mail_reply_to

    msg.set_content(
        f"Copia de seguridad de articulo enviada desde /admin.\n\n"
        f"Titulo: {clean_title}\n"
        f"Slug: {clean_slug or 'N/A'}\n\n"
        f"Contenido (texto):\n{plain}\n"
    )
    msg.add_alternative(
        "<div style=\"font-family:Georgia,'Times New Roman',serif;max-width:760px;margin:auto;line-height:1.7;color:#2a2342\">"
        "<p><strong>Copia de seguridad de articulo enviada desde /admin</strong></p>"
        f"<p><strong>Titulo:</strong> {clean_title}<br><strong>Slug:</strong> {clean_slug or 'N/A'}</p>"
        "<hr style=\"border:0;border-top:1px solid #e1d8c2;margin:16px 0\" />"
        f"{html}"
        "</div>",
        subtype="html",
    )

    return _deliver_message(msg)


def build_message(booking: Booking) -> EmailMessage:
    """Compose the multipart (text + HTML) email carrying the video link."""
    msg = EmailMessage()
    msg["Subject"] = f"Tu enlace de videollamada Â· {settings.business_name}"
    msg["From"] = settings.effective_sender
    msg["To"] = booking.email
    if settings.mail_reply_to:
        msg["Reply-To"] = settings.mail_reply_to

    name = (booking.full_name or "").replace("<", "").replace(">", "")
    link = booking.video_url or ""
    ref = booking.reference

    msg.set_content(
        f"Hola {name},\n\n"
        f"Hemos confirmado la recepcion de tu pago. Â¡Gracias!\n\n"
        f"Este es tu enlace privado para la videollamada con {settings.business_name}:\n"
        f"{link}\n\n"
        f"El enlace es personal; por favor no lo compartas.\n\n"
        f"Referencia: {ref}\n\n"
        f"Con carino,\n{settings.business_name}\n"
    )

    msg.add_alternative(
        "<div style=\"font-family:Georgia,'Times New Roman',serif;color:#2a2342;"
        "line-height:1.6;max-width:520px;margin:auto\">"
        f"<p>Hola <strong>{name}</strong>,</p>"
        "<p>Hemos confirmado la recepci&oacute;n de tu pago. &iexcl;Gracias!</p>"
        f"<p>Este es tu enlace privado para la videollamada con "
        f"<strong>{settings.business_name}</strong>:</p>"
        f"<p style=\"margin:22px 0\"><a href=\"{link}\" "
        "style=\"background:#e8c66b;color:#1a1533;padding:13px 24px;border-radius:999px;"
        "text-decoration:none;font-weight:bold;display:inline-block\">"
        "Entrar a la videollamada</a></p>"
        f"<p style=\"font-size:13px;color:#6b6385\">o copia este enlace:<br>{link}</p>"
        "<p style=\"font-size:13px;color:#6b6385\">El enlace es personal; "
        "por favor no lo compartas.</p>"
        f"<p style=\"font-size:13px;color:#6b6385\">Referencia: {ref}</p>"
        f"<p>Con cari&ntilde;o,<br>{settings.business_name}</p>"
        "</div>",
        subtype="html",
    )
    return msg


def send_video_link(booking: Booking) -> Tuple[bool, str]:
    """Send the video link to the client. Returns ``(ok, human_detail)``.

    Never raises: any SMTP error is logged and reported back as a string so the
    admin can retry from the panel.
    """
    if not (settings.resend_enabled or settings.mail_enabled):
        return False, "Correo no configurado"
    if not booking.video_url:
        return False, "Sin enlace que enviar"
    if not booking.email:
        return False, "Sin correo del cliente"

    message = build_message(booking)
    ok, info = _deliver_message(message)
    if not ok:
        logger.warning("Email send failed for %s: %s", booking.reference, info)
        return ok, info

    logger.info("Video link emailed for booking %s", booking.reference)
    return True, "Enviado"


def build_payment_received_message(booking: Booking) -> EmailMessage:
    """Compose a payment-received confirmation for the client."""
    msg = EmailMessage()
    msg["Subject"] = f"Pago recibido Â· {settings.business_name}"
    msg["From"] = settings.effective_sender
    msg["To"] = booking.email
    if settings.mail_reply_to:
        msg["Reply-To"] = settings.mail_reply_to

    name = (booking.full_name or "").replace("<", "").replace(">", "")
    method = booking.payment_method or "en validacion"
    ref = booking.reference

    msg.set_content(
        f"Hola {name},\n\n"
        "Hemos recibido tu pago correctamente.\n"
        "Tu consulta ahora esta en validacion y te enviaremos por correo el enlace privado "
        "de videollamada una vez confirmada.\n\n"
        f"Metodo reportado: {method}\n"
        f"Referencia: {ref}\n\n"
        f"Con carino,\n{settings.business_name}\n"
    )
    return msg


def _build_business_notice(booking: Booking, subject: str, intro: str, details: str) -> EmailMessage:
    """Compose a plain business notification email for Adelinemagica team."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.effective_sender
    msg["To"] = settings.notify_recipient
    if settings.mail_reply_to:
        msg["Reply-To"] = settings.mail_reply_to

    appt_date = booking.appointment_date.isoformat() if booking.appointment_date else "N/A"
    appt_time = booking.appointment_time.strftime("%H:%M") if booking.appointment_time else "N/A"
    paid = booking.paid_at.isoformat() if booking.paid_at else "N/A"

    body = (
        f"{intro}\n\n"
        f"Referencia: {booking.reference}\n"
        f"Cliente: {booking.full_name}\n"
        f"Email: {booking.email}\n"
        f"Plan: {booking.plan}\n"
        f"Estado: {booking.status}\n"
        f"Importe: {booking.amount} {booking.currency}\n"
        f"Metodo de pago: {booking.payment_method or 'N/A'}\n"
        f"Cita: {appt_date} {appt_time}\n"
        f"Pago confirmado: {paid}\n\n"
        f"Detalle:\n{details}\n"
    )
    msg.set_content(body)
    return msg


def _smtp_send(msg: EmailMessage) -> Tuple[bool, str]:
    """Send a prepared email over configured SMTP, never raising."""
    host, port, timeout = settings.smtp_host, settings.smtp_port, settings.smtp_timeout
    try:
        if settings.smtp_use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, timeout=timeout, context=context) as server:
                if settings.smtp_user:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as server:
                server.ehlo()
                if settings.smtp_use_tls:
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
                if settings.smtp_user:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
    except Exception as exc:  # noqa: BLE001
        return False, f"Error SMTP: {type(exc).__name__}"
    return True, "Enviado"


def _extract_bodies(msg: EmailMessage) -> Tuple[str, str]:
    """Extract plain and html bodies from an EmailMessage."""
    plain, html = "", ""
    if msg.is_multipart():
        plain_part = msg.get_body(preferencelist=("plain",))
        html_part = msg.get_body(preferencelist=("html",))
        if plain_part is not None:
            plain = plain_part.get_content()
        if html_part is not None:
            html = html_part.get_content()
    else:
        plain = msg.get_content()
    return plain or "", html or ""


def _resend_send(msg: EmailMessage) -> Tuple[bool, str]:
    """Send email using Resend HTTP API, never raising."""
    plain, html = _extract_bodies(msg)
    payload = {
        "from": settings.resend_from,
        "to": [str(msg.get("To", "")).strip()],
        "subject": str(msg.get("Subject", "")).strip(),
        "text": plain,
    }
    if html:
        payload["html"] = html
    reply_to = str(msg.get("Reply-To", "")).strip()
    if reply_to:
        payload["reply_to"] = reply_to

    body = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(
        "https://api.resend.com/emails",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {settings.resend_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"{settings.business_name}/1.0 (+https://adelinemagica.com)",
        },
    )
    try:
        with urlrequest.urlopen(req, timeout=settings.resend_timeout) as res:
            if 200 <= getattr(res, "status", 200) < 300:
                return True, "Enviado"
            return False, f"Error Resend: HTTP {getattr(res, 'status', 'unknown')}"
    except urlerror.HTTPError as exc:
        detail = ""
        try:
            raw = exc.read().decode("utf-8", errors="ignore").strip()
            if raw:
                detail = f" ({raw[:240]})"
        except Exception:
            detail = ""
        return False, f"Error Resend: HTTP {exc.code}{detail}"
    except Exception as exc:  # noqa: BLE001
        return False, f"Error Resend: {type(exc).__name__}"


def _deliver_message(msg: EmailMessage) -> Tuple[bool, str]:
    """Deliver message preferring Resend, then SMTP fallback when possible."""
    if settings.resend_enabled:
        ok, info = _resend_send(msg)
        if ok or not settings.mail_enabled:
            return ok, info
    if settings.mail_enabled:
        return _smtp_send(msg)
    return False, "Correo no configurado"


def send_payment_received_confirmation(booking: Booking) -> Tuple[bool, str]:
    """Email the client to confirm that payment has been received."""
    if not (settings.resend_enabled or settings.mail_enabled):
        return False, "Correo no configurado"
    if not booking.email:
        return False, "Sin correo del cliente"

    msg = build_payment_received_message(booking)
    ok, info = _deliver_message(msg)
    if ok:
        logger.info("Payment confirmation emailed for booking %s", booking.reference)
    else:
        logger.warning("Payment confirmation failed for %s: %s", booking.reference, info)
    return ok, info


def send_business_notice(booking: Booking, event: str, details: str) -> Tuple[bool, str]:
    """Notify business mailbox on booking/payment lifecycle events."""
    if not (settings.resend_enabled or settings.mail_enabled):
        return False, "Correo no configurado"
    if not settings.notify_recipient:
        return False, "Destinatario de notificacion no configurado"

    subject = f"[{settings.business_name}] {event} Â· {booking.reference}"
    intro = f"Nuevo evento de negocio registrado: {event}."
    msg = _build_business_notice(booking, subject, intro, details)
    ok, info = _deliver_message(msg)
    if ok:
        logger.info("Business notice sent for %s (%s)", booking.reference, event)
    else:
        logger.warning("Business notice failed for %s (%s): %s", booking.reference, event, info)
    return ok, info


def send_contact_messages(
    first_name: str,
    last_name: str,
    email: str,
    message_text: str,
) -> Tuple[bool, str]:
    """Send a contact request to business mailbox and an acknowledgement to user."""
    if not (settings.resend_enabled or settings.mail_enabled):
        return False, "Correo no configurado"
    if not settings.notify_recipient:
        return False, "Destinatario de notificacion no configurado"

    full_name = f"{first_name} {last_name}".strip()
    clean_name = full_name.replace("<", "").replace(">", "")

    business_msg = EmailMessage()
    business_msg["Subject"] = f"[{settings.business_name}] Nueva solicitud de contacto"
    business_msg["From"] = settings.effective_sender or settings.resend_from
    business_msg["To"] = settings.notify_recipient
    business_msg["Reply-To"] = email
    business_msg.set_content(
        "Nueva solicitud de informacion recibida desde contact.html\n\n"
        f"Nombre: {clean_name}\n"
        f"Email: {email}\n\n"
        f"Mensaje:\n{message_text}\n"
    )

    ok_business, info_business = _deliver_message(business_msg)
    if not ok_business:
        return False, info_business

    user_msg = EmailMessage()
    user_msg["Subject"] = f"Hemos recibido tu mensaje Â· {settings.business_name}"
    user_msg["From"] = settings.effective_sender or settings.resend_from
    user_msg["To"] = email
    if settings.mail_reply_to:
        user_msg["Reply-To"] = settings.mail_reply_to
    user_msg.set_content(
        f"Hola {clean_name},\n\n"
        "Gracias por escribirnos. Hemos recibido tu solicitud de informacion "
        "sobre nuestros servicios y te responderemos por correo lo antes posible.\n\n"
        "Resumen de tu mensaje:\n"
        f"{message_text}\n\n"
        f"Con carino,\n{settings.business_name}\n"
    )

    ok_user, info_user = _deliver_message(user_msg)
    if not ok_user:
        return False, info_user

    return True, "Solicitud enviada"


def send_direct_stripe_payment_notice(session: dict, intake_data: dict = None) -> Tuple[bool, str]:
    """Notify business inbox for paid Stripe checkouts not tied to Booking rows."""
    if not (settings.resend_enabled or settings.mail_enabled):
        return False, "Correo no configurado"
    if not settings.notify_recipient:
        return False, "Destinatario de notificacion no configurado"

    customer = session.get("customer_details") or {}
    metadata = session.get("metadata") or {}
    intake_data = intake_data or {}
    amount_total = session.get("amount_total")
    currency = (session.get("currency") or "").upper()
    created_ts = session.get("created")
    paid_at = "N/A"
    if isinstance(created_ts, int):
        paid_at = datetime.fromtimestamp(created_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    amount_human = "N/A"
    if isinstance(amount_total, int):
        amount_human = f"{amount_total / 100:.2f} {currency or ''}".strip()

    msg = EmailMessage()
    msg["Subject"] = f"[{settings.business_name}] Pago Stripe recibido (directo)"
    msg["From"] = settings.effective_sender or settings.resend_from
    msg["To"] = settings.notify_recipient
    if settings.mail_reply_to:
        msg["Reply-To"] = settings.mail_reply_to

    service = metadata.get("service") or intake_data.get("service") or "N/A"
    first_name = metadata.get("first_name") or intake_data.get("first_name") or ""
    last_name = metadata.get("last_name") or intake_data.get("last_name") or ""
    form_email = metadata.get("email") or intake_data.get("email") or "N/A"
    appt_date = metadata.get("appointment_date") or intake_data.get("appointment_date") or "N/A"
    appt_time = metadata.get("appointment_time") or intake_data.get("appointment_time") or "N/A"
    notes = metadata.get("notes") or intake_data.get("notes") or "N/A"
    notes_block = str(notes).strip() or "N/A"

    msg.set_content(
        "Pago Stripe confirmado para un enlace directo.\n\n"
        "=== Datos de pago ===\n"
        f"Fecha y hora de pago: {paid_at}\n"
        f"Nombre cliente: {customer.get('name') or 'N/A'}\n"
        f"Email cliente: {customer.get('email') or 'N/A'}\n"
        f"Monto: {amount_human}\n"
        "\n=== Datos del formulario ===\n"
        f"Servicio: {service}\n"
        f"Nombre formulario: {first_name} {last_name}\n"
        f"Email formulario: {form_email}\n"
        f"Fecha cita: {appt_date}\n"
        f"Hora cita: {appt_time}\n"
        "\nDetalles de la solicitud:\n"
        f"{notes_block}\n"
        "\n=== Stripe ===\n"
        f"Session ID: {session.get('id') or 'N/A'}\n"
        f"Payment Link ID: {session.get('payment_link') or 'N/A'}\n"
    )

    return _deliver_message(msg)


def send_direct_stripe_customer_confirmation(session: dict, intake_data: dict = None) -> Tuple[bool, str]:
    """Send a confirmation email to the direct Stripe payer after payment."""
    if not (settings.resend_enabled or settings.mail_enabled):
        return False, "Correo no configurado"

    customer = session.get("customer_details") or {}
    intake_data = intake_data or {}
    to_email = customer.get("email") or intake_data.get("email")
    if not to_email:
        return False, "Email cliente no disponible"

    amount_total = session.get("amount_total")
    currency = (session.get("currency") or "").upper()
    amount_human = "N/A"
    if isinstance(amount_total, int):
        amount_human = f"{amount_total / 100:.2f} {currency or ''}".strip()

    service = intake_data.get("service") or "consulta"
    appointment_date = intake_data.get("appointment_date") or "por confirmar"
    appointment_time = intake_data.get("appointment_time") or "por confirmar"
    notes = intake_data.get("notes") or ""
    name = customer.get("name") or f"{intake_data.get('first_name', '')} {intake_data.get('last_name', '')}".strip() or ""

    msg = EmailMessage()
    msg["Subject"] = f"Pago recibido · {settings.business_name}"
    msg["From"] = settings.effective_sender or settings.resend_from
    msg["To"] = to_email
    if settings.mail_reply_to:
        msg["Reply-To"] = settings.mail_reply_to

    msg.set_content(
        f"Hola {name or 'consultante'},\n\n"
        "Hemos recibido tu pago correctamente.\n"
        f"Servicio: {service}\n"
        f"Monto: {amount_human}\n"
        f"Fecha solicitada: {appointment_date}\n"
        f"Hora solicitada: {appointment_time}\n"
        f"Notas: {notes or 'N/A'}\n\n"
        "Te escribiremos para confirmar tu cita.\n\n"
        f"Con cariño,\n{settings.business_name}\n"
    )
    return _deliver_message(msg)


def send_direct_stripe_appointment_details(
    session: dict,
    intake_data: dict,
    appointment_data: dict,
) -> Tuple[bool, str]:
    """Send appointment date/time and Google Calendar/Meet links to business and payer."""
    if not (settings.resend_enabled or settings.mail_enabled):
        return False, "Correo no configurado"

    customer = session.get("customer_details") or {}
    to_user = (customer.get("email") or intake_data.get("email") or "").strip()
    if not to_user:
        return False, "Email cliente no disponible"
    to_business = settings.notify_recipient
    if not to_business:
        return False, "Destinatario de negocio no configurado"

    video_url = (appointment_data.get("video_url") or "").strip()
    calendar_url = (appointment_data.get("google_calendar_url") or "").strip()
    start_at = appointment_data.get("start_at") or ""
    end_at = appointment_data.get("end_at") or ""
    tentative = str(appointment_data.get("tentative") or "false").lower() == "true"
    service = intake_data.get("service") or "consulta"
    full_name = f"{intake_data.get('first_name', '')} {intake_data.get('last_name', '')}".strip()

    def _pretty_dt(value: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return "N/A"
        try:
            dt = datetime.fromisoformat(raw)
            return dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            return raw

    start_human = _pretty_dt(start_at)
    end_human = _pretty_dt(end_at)
    requested_date = (intake_data.get("appointment_date") or "").strip() or "N/A"
    requested_time = (intake_data.get("appointment_time") or "").strip() or "N/A"
    full_notes = (intake_data.get("notes") or "").strip() or "N/A"
    amount_total = session.get("amount_total")
    currency = (session.get("currency") or "").upper()
    amount_human = "N/A"
    if isinstance(amount_total, int):
        amount_human = f"{amount_total / 100:.2f} {currency or ''}".strip()
    created_ts = session.get("created")
    paid_at = "N/A"
    if isinstance(created_ts, int):
        paid_at = datetime.fromtimestamp(created_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    business_msg = EmailMessage()
    business_msg["Subject"] = f"[{settings.business_name}] Cita creada + Google Calendar/Meet"
    business_msg["From"] = settings.effective_sender or settings.resend_from
    business_msg["To"] = to_business
    if settings.mail_reply_to:
        business_msg["Reply-To"] = settings.mail_reply_to
    business_msg.set_content(
        "Se creo automaticamente una cita tras pago Stripe.\n\n"
        "=== CITA CREADA ===\n"
        f"Estado cita: {'A confirmar (tentative)' if tentative else 'Confirmada'}\n"
        f"Inicio (agenda): {start_human}\n"
        f"Fin (agenda): {end_human}\n"
        f"Evento Google Calendar: {calendar_url or 'N/A'}\n"
        f"Enlace Google Meet: {video_url or 'N/A'}\n"
        "\n=== DATOS CLIENTE (CHECKOUT) ===\n"
        f"Nombre checkout: {customer.get('name') or 'N/A'}\n"
        f"Email checkout: {customer.get('email') or to_user or 'N/A'}\n"
        "\n=== DATOS FORMULARIO (SITIO) ===\n"
        f"Servicio: {service}\n"
        f"Nombre formulario: {full_name or 'N/A'}\n"
        f"Email formulario: {intake_data.get('email') or 'N/A'}\n"
        f"Fecha solicitada: {requested_date}\n"
        f"Hora solicitada: {requested_time}\n"
        "\nPreguntas y respuestas:\n"
        f"{full_notes}\n"
        "\n=== PAGO STRIPE ===\n"
        f"Monto: {amount_human}\n"
        f"Fecha de pago: {paid_at}\n"
        f"Payment status: {session.get('payment_status') or 'N/A'}\n"
        f"Stripe Session: {session.get('id') or 'N/A'}\n"
        f"Payment Link ID: {session.get('payment_link') or 'N/A'}\n"
        "\nNota: la invitacion Google Calendar se envia automaticamente a los asistentes.\n"
    )
    ok_business, info_business = _deliver_message(business_msg)
    if not ok_business:
        return False, info_business

    user_msg = EmailMessage()
    user_msg["Subject"] = f"Tu cita esta confirmada + Google Meet · {settings.business_name}"
    user_msg["From"] = settings.effective_sender or settings.resend_from
    user_msg["To"] = to_user
    if settings.mail_reply_to:
        user_msg["Reply-To"] = settings.mail_reply_to
    user_msg.set_content(
        f"Hola {customer.get('name') or full_name or 'consultante'},\n\n"
        "Tu pago fue confirmado y tu cita ya esta programada.\n"
        f"Estado de cita: {'A confirmar (horario provisional)' if tentative else 'Confirmada'}\n"
        f"Servicio: {service}\n"
        f"Fecha y hora: {start_human}\n"
        f"Finaliza: {end_human}\n"
        f"Evento Google Calendar: {calendar_url or 'N/A'}\n"
        f"Enlace Google Meet: {video_url or 'N/A'}\n\n"
        "Recomendacion: entra 5 minutos antes para verificar audio y camara.\n\n"
        f"Con cariño,\n{settings.business_name}\n"
    )
    if video_url:
        calendar_html = f"<p><a href=\"{calendar_url}\">Abrir evento en Google Calendar</a></p>" if calendar_url else ""
        html_body = (
            "<div style=\"font-family:Georgia,'Times New Roman',serif;color:#2a2342;line-height:1.6;max-width:560px;margin:auto\">"
            f"<p>Hola <strong>{customer.get('name') or full_name or 'consultante'}</strong>,</p>"
            "<p>Tu pago fue confirmado y tu cita ya esta programada.</p>"
            f"<p><strong>Estado:</strong> {'A confirmar (horario provisional)' if tentative else 'Confirmada'}<br>"
            f"<strong>Servicio:</strong> {service}<br>"
            f"<strong>Fecha y hora:</strong> {start_human}<br>"
            f"<strong>Finaliza:</strong> {end_human}</p>"
            f"{calendar_html}"
            f"<p style=\"margin:22px 0\"><a href=\"{video_url}\" style=\"background:#e8c66b;color:#1a1533;padding:13px 24px;border-radius:999px;text-decoration:none;font-weight:bold;display:inline-block\">Entrar a la videollamada</a></p>"
            f"<p style=\"font-size:13px;color:#6b6385\">Si no funciona el boton, usa este enlace:<br>{video_url}</p>"
            "<p style=\"font-size:13px;color:#6b6385\">Recomendacion: entra 5 minutos antes para verificar audio y camara.</p>"
            f"<p>Con cariño,<br>{settings.business_name}</p>"
            "</div>"
        )
        user_msg.add_alternative(
            html_body,
            subtype="html",
        )
    return _deliver_message(user_msg)


def send_stripe_invoice_notice(invoice: dict, event_type: str) -> Tuple[bool, str]:
    """Notify business inbox on Stripe invoice lifecycle events."""
    if not (settings.resend_enabled or settings.mail_enabled):
        return False, "Correo no configurado"
    if not settings.notify_recipient:
        return False, "Destinatario de notificacion no configurado"

    amount_paid = invoice.get("amount_paid")
    amount_due = invoice.get("amount_due")
    currency = (invoice.get("currency") or "").upper()
    customer_email = invoice.get("customer_email") or "N/A"
    status = invoice.get("status") or "N/A"
    due_ts = invoice.get("due_date")
    due_human = "N/A"
    if isinstance(due_ts, int):
        due_human = datetime.fromtimestamp(due_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    paid_human = "N/A"
    if isinstance(amount_paid, int):
        paid_human = f"{amount_paid / 100:.2f} {currency}".strip()
    due_amount_human = "N/A"
    if isinstance(amount_due, int):
        due_amount_human = f"{amount_due / 100:.2f} {currency}".strip()

    msg = EmailMessage()
    msg["Subject"] = f"[{settings.business_name}] Stripe invoice {event_type}"
    msg["From"] = settings.effective_sender or settings.resend_from
    msg["To"] = settings.notify_recipient
    if settings.mail_reply_to:
        msg["Reply-To"] = settings.mail_reply_to

    msg.set_content(
        "Evento de factura Stripe detectado.\n\n"
        f"Evento: {event_type}\n"
        f"Invoice ID: {invoice.get('id') or 'N/A'}\n"
        f"Estado: {status}\n"
        f"Email cliente: {customer_email}\n"
        f"Importe pagado: {paid_human}\n"
        f"Importe pendiente: {due_amount_human}\n"
        f"Vencimiento: {due_human}\n"
        f"Hosted invoice URL: {invoice.get('hosted_invoice_url') or 'N/A'}\n"
    )
    return _deliver_message(msg)

