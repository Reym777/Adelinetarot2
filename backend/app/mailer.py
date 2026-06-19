"""Transactional email (SMTP) used to deliver the private video-call link.

Design / security notes:
* The link to the video call is delivered ONLY by email, and only after
  AdelineTarot has confirmed she received the payment (admin validation).
* SMTP credentials come exclusively from the environment (see ``config.py``);
  nothing is hardcoded.
* The recipient address is an ``EmailStr`` validated at booking time and the
  display name is sanitised (no ``<>@``), which prevents header injection.
* Sending failures are reported back to the caller (and surfaced in the admin
  panel) instead of raising, so validating a payment never 500s on a mail glitch.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Tuple

from .config import settings
from .models import Booking

logger = logging.getLogger("adelinetarot.mailer")


def build_message(booking: Booking) -> EmailMessage:
    """Compose the multipart (text + HTML) email carrying the video link."""
    msg = EmailMessage()
    msg["Subject"] = f"Tu enlace de videollamada · {settings.business_name}"
    msg["From"] = settings.effective_sender
    msg["To"] = booking.email
    if settings.mail_reply_to:
        msg["Reply-To"] = settings.mail_reply_to

    name = (booking.full_name or "").replace("<", "").replace(">", "")
    link = booking.video_url or ""
    ref = booking.reference

    msg.set_content(
        f"Hola {name},\n\n"
        f"Hemos confirmado la recepcion de tu pago. ¡Gracias!\n\n"
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
    if not settings.mail_enabled:
        return False, "SMTP no configurado"
    if not booking.video_url:
        return False, "Sin enlace que enviar"
    if not booking.email:
        return False, "Sin correo del cliente"

    message = build_message(booking)
    host, port, timeout = settings.smtp_host, settings.smtp_port, settings.smtp_timeout
    try:
        if settings.smtp_use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, timeout=timeout, context=context) as server:
                if settings.smtp_user:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as server:
                server.ehlo()
                if settings.smtp_use_tls:
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
                if settings.smtp_user:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(message)
    except Exception as exc:  # noqa: BLE001 — report, never crash the request
        logger.warning("Email send failed for %s: %s", booking.reference, exc)
        return False, f"Error SMTP: {type(exc).__name__}"

    logger.info("Video link emailed for booking %s", booking.reference)
    return True, "Enviado"
