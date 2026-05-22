"""
services/acuity.py — Cliente para la API de Acuity Scheduling.
Docs: https://developers.acuityscheduling.com/reference/appointment-get
Autenticación: HTTP Basic (user_id:api_key).
"""
import base64
import hashlib
import hmac
import httpx
import config

_BASE    = "https://acuityscheduling.com/api/v1"
_TIMEOUT = 30


def _auth_headers() -> dict:
    token = base64.b64encode(
        f"{config.ACUITY_USER_ID}:{config.ACUITY_API_KEY}".encode()
    ).decode()
    return {"Authorization": f"Basic {token}"}


async def get_appointment(appointment_id: str | int) -> dict:
    """Obtiene los detalles completos de una cita de Acuity."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(
            f"{_BASE}/appointments/{appointment_id}",
            headers=_auth_headers(),
        )
        r.raise_for_status()
        return r.json()


def verify_signature(body: bytes, signature_header: str) -> bool:
    """
    Verifica la firma HMAC-SHA256 que Acuity incluye en X-Acuity-Signature.
    Devuelve True si es válida o si ACUITY_WEBHOOK_SECRET no está configurado.
    """
    if not config.ACUITY_WEBHOOK_SECRET:
        return True
    expected = base64.b64encode(
        hmac.new(
            config.ACUITY_WEBHOOK_SECRET.encode(),
            body,
            hashlib.sha256,
        ).digest()
    ).decode()
    return hmac.compare_digest(expected, signature_header or "")
