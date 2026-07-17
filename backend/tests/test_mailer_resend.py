from datetime import date

from app import mailer
from app.models import Booking


class _DummyResponse:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _booking() -> Booking:
    return Booking(
        reference="REF123",
        public_token="token123",
        full_name="Ada Lovelace",
        email="ada@example.com",
        birth_date=date(1990, 1, 1),
        birth_place="Lima",
        plan="pen",
        currency="PEN",
        amount=20.0,
        charge_currency="USD",
        charge_amount=6.0,
        status="pending",
        video_url="https://meet.jit.si/room-123",
    )


def test_send_video_link_uses_resend(monkeypatch):
    calls = {"count": 0}

    def fake_urlopen(req, timeout=0):
        calls["count"] += 1
        assert req.full_url == "https://api.resend.com/emails"
        assert timeout == 7
        return _DummyResponse(status=202)

    monkeypatch.setattr(mailer.settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(mailer.settings, "resend_from", "Adeline <onboarding@resend.dev>")
    monkeypatch.setattr(mailer.settings, "resend_timeout", 7)
    monkeypatch.setattr(mailer.settings, "smtp_host", "")
    monkeypatch.setattr(mailer.settings, "smtp_from", "")
    monkeypatch.setattr(mailer.urlrequest, "urlopen", fake_urlopen)

    ok, info = mailer.send_video_link(_booking())

    assert ok is True
    assert info == "Enviado"
    assert calls["count"] == 1


def test_send_video_link_resend_fallback_to_smtp(monkeypatch):
    monkeypatch.setattr(mailer.settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(mailer.settings, "resend_from", "Adeline <onboarding@resend.dev>")
    monkeypatch.setattr(mailer.settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(mailer.settings, "smtp_from", "noreply@example.com")

    def fake_urlopen(req, timeout=0):
        raise RuntimeError("network down")

    def fake_smtp_send(msg):
        return True, "Enviado"

    monkeypatch.setattr(mailer.urlrequest, "urlopen", fake_urlopen)
    monkeypatch.setattr(mailer, "_smtp_send", fake_smtp_send)

    ok, info = mailer.send_video_link(_booking())

    assert ok is True
    assert info == "Enviado"


def test_send_video_link_requires_provider(monkeypatch):
    monkeypatch.setattr(mailer.settings, "resend_api_key", "")
    monkeypatch.setattr(mailer.settings, "resend_from", "")
    monkeypatch.setattr(mailer.settings, "smtp_host", "")
    monkeypatch.setattr(mailer.settings, "smtp_from", "")

    ok, info = mailer.send_video_link(_booking())

    assert ok is False
    assert info == "Correo no configurado"
