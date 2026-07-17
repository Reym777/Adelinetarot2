from __future__ import annotations

from fastapi import APIRouter, Depends

from ..mailer import send_contact_messages
from ..schemas import ContactRequest, ContactResponse
from ..security import write_rate_limit

router = APIRouter(prefix="/api/contact", tags=["contact"])


@router.post("", response_model=ContactResponse)
def send_contact_request(
    payload: ContactRequest,
    _: None = Depends(write_rate_limit),
) -> ContactResponse:
    # Honeypot trap: pretend success to bots while ignoring their payload.
    if payload.website:
        return ContactResponse(ok=True, message="Mensaje recibido.")

    ok, info = send_contact_messages(
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=str(payload.email),
        message_text=payload.message,
    )
    if not ok:
        return ContactResponse(ok=False, message=f"No fue posible enviar el mensaje: {info}")

    return ContactResponse(
        ok=True,
        message="Mensaje enviado. Te responderemos por correo pronto.",
    )
