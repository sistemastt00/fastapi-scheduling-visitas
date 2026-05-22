"""
handlers/visita_modificada.py — Lógica para citas modificadas (blueprint 02).
Flujo: esperar 240 s → buscar visita por ID Acuity → actualizar fecha/hora y título.
"""
import asyncio
import datetime
import logging
import re

import config
import state
from services import acuity as acuity_svc
from services import bitrix

logger = logging.getLogger("scheduling-visitas")

_DELAY_SECONDS = 240  # espera del blueprint original para evitar condiciones de carrera


def _format_datetime(dt_str: str) -> str:
    if not dt_str:
        return ""
    return re.sub(r"([+-])(\d{2})(\d{2})$", r"\1\2:\3", dt_str)


async def run(payload: dict) -> dict:
    """
    payload: datos del webhook de Acuity (acción 'appointment.rescheduled').
    Espera 240 s antes de ejecutar (replica el FunctionSleep del blueprint).
    """
    appointment_id = payload.get("id")
    logger.info(f"[visita_modificada] appointment_id={appointment_id} — esperando {_DELAY_SECONDS}s")
    await asyncio.sleep(_DELAY_SECONDS)

    # 1. Detalles actualizados de la cita
    appt     = await acuity_svc.get_appointment(appointment_id)
    first    = appt.get("firstName", "")
    last     = appt.get("lastName", "")
    email    = appt.get("email", "")
    tipo     = appt.get("type", "")
    fecha_dt = _format_datetime(appt.get("datetime", ""))
    title    = f"Actualizada: Visita: {first} {last} - {tipo} - {appt.get('date', '')} {appt.get('time', '')}"
    logger.info(f"[visita_modificada] {first} {last} | {tipo} | {fecha_dt}")

    # 2. Buscar visita en Bitrix24 por ID de Acuity
    visita = await bitrix.find_visita_by_acuity_id(appointment_id)
    if not visita:
        msg = f"Visita no encontrada para appointment_id={appointment_id}"
        logger.warning(f"[visita_modificada] {msg}")
        _record_summary(appointment_id, f"{first} {last}", email, "modificada", msg, "")
        return {"warning": msg}

    item_id = visita.get("id")

    # 3. Actualizar fecha, hora y título
    await bitrix.update_crm_item(
        config.BITRIX_ENTITY_VISITAS, item_id,
        {
            "stageId":                      config.BITRIX_STAGE_NEW,
            "title":                        title,
            config.BX_FIELD_FECHA_HORA:     fecha_dt,
            config.BX_FIELD_FECHA_HORA_ALT: fecha_dt,
        },
    )
    logger.info(f"[visita_modificada] Visita actualizada: ID={item_id}")

    _record_summary(appointment_id, f"{first} {last}", email, "modificada",
                    f"Visita actualizada | ID: {item_id}", str(item_id))
    return {"visita_id": item_id, "updated": True}


def _record_summary(appt_id, client, email, action, result, bitrix_id):
    state.summaries.appendleft({
        "time":           datetime.datetime.now().strftime("%d/%m %H:%M:%S"),
        "appointment_id": str(appt_id),
        "client":         client,
        "email":          email,
        "action":         action,
        "result":         result,
        "bitrix_id":      bitrix_id,
    })
