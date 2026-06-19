"""AdelineTarot secure backend (FastAPI).

A small, security-focused API behind the AdelineTarot website. It captures
birth data, computes an astrological natal chart and a tarot reading, generates
a detailed report and creates a unique video-call link shared by the client and
the admin (AdelineTarot) once payment is confirmed.
"""

__all__ = ["__version__"]

__version__ = "1.0.0"
