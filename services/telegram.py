"""
services/telegram.py — Notificaciones de error por Telegram.
Llama al Bot API de forma silenciosa: nunca rompe el flujo principal.
"""
import httpx
import config


async def send_alert(msg: str) -> None:
    """
    Envía un mensaje de alerta al canal de Telegram configurado.
    Si TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no están definidos, no hace nada.
    Los fallos de red / API se capturan y se ignoran.
    """
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            await c.post(
                f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id":    config.TELEGRAM_CHAT_ID,
                    "text":       msg,
                    "parse_mode": "Markdown",
                },
            )
    except Exception:
        pass  # nunca romper el flujo por un fallo de Telegram
