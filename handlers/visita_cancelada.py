"""
handlers/visita_cancelada.py — Lógica para citas canceladas (blueprint 03).
Flujo: buscar visita por ID Acuity → marcar etapa como FAIL.
"""
import datetime
import logging

import config
import state
from services import acuity as acuity_svc
from services import bitrix

logger = logging.getLogger("scheduling-visitas")


async def run(payload: dict) -> dict:
    """
    payload: datos del webhook de Acuity (acción 'appointment.canceled').
    Retorna resumen con visita_id actualizado a FAIL.
    """
    appointment_id = payload.get("id")
    logger.info(f"[visita_cancelada] appointment_id={appointment_id}")

    # 1. Detalles de la cita
    appt  = await acuity_svc.get_appointment(appointment_id)
    first = appt.get("firstName", "")
    last  = appt.get("lastName", "")
    email = appt.get("email", "")
    logger.info(f"[visita_cancelada] {first} {last} | {appt.get('type', '')}")

    # 2. Buscar visita en Bitrix24
    visita = await bitrix.find_visita_by_acuity_id(appointment_id)
    if not visita:
        msg = f"Visita no encontrada para appointment_id={appointment_id}"
        logger.warning(f"[visita_cancelada] {msg}")
        _record_summary(appointment_id, f"{first} {last}", email, "cancelada", msg, "")
        return {"warning": msg}

    item_id       = visita.get("id")
    current_stage = visita.get("stageId", "")

    # Ya está en FAIL — evitar llamada innecesaria (igual que la condición del blueprint)
    if current_stage == config.BITRIX_STAGE_FAIL:
        msg = f"Visita ID={item_id} ya estaba en FAIL — sin cambios"
        logger.info(f"[visita_cancelada] {msg}")
        _record_summary(appointment_id, f"{first} {last}", email, "cancelada", msg, str(item_id))
        return {"visita_id": item_id, "stage": current_stage, "skipped": True}

    # 3. Actualizar etapa a FAIL
    await bitrix.update_crm_item(
        config.BITRIX_ENTITY_VISITAS, item_id,
        {"stageId": config.BITRIX_STAGE_FAIL},
    )
    logger.info(f"[visita_cancelada] Visita marcada FAIL: ID={item_id}")

    _record_summary(appointment_id, f"{first} {last}", email, "cancelada",
                    f"Visita FAIL | ID: {item_id}", str(item_id))
    return {"visita_id": item_id, "stage": config.BITRIX_STAGE_FAIL}


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
