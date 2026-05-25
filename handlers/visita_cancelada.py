"""
handlers/visita_cancelada.py — Blueprint 03: Visita Cancelada.

Flujo exacto del blueprint (Make.com):

  Trigger: watchAppointments (cualquier evento)
    └─ getAppointment
         └─ FILTRO: canceled == "true"
              └─ crm.item.list (buscar visita por ufCrm31_1745787119410)
                   └─ FILTRO: stageId != "DT182_55:FAIL" AND total != 0
                        └─ crm.item.update (stageId → DT182_55:FAIL)
"""
import logging

import config
from handlers.shared import record_summary
from services import acuity as acuity_svc
from services import bitrix

logger = logging.getLogger("scheduling-visitas")


async def run(payload: dict) -> dict:
    appointment_id = payload.get("id")
    logger.info(f"[visita_cancelada] appointment_id={appointment_id}")

    # ── getAppointment ────────────────────────────────────────────────────────
    appt  = await acuity_svc.get_appointment(appointment_id)
    first = appt.get("firstName", "")
    last  = appt.get("lastName", "")
    email = appt.get("email", "")
    logger.info(f"[visita_cancelada] {first} {last} | {appt.get('type', '')}")

    # ── FILTRO: canceled == "true" ────────────────────────────────────────────
    if str(appt.get("canceled", "false")).lower() != "true":
        msg = f"Cita {appointment_id} no está cancelada (canceled={appt.get('canceled')}) — ignorando"
        logger.info(f"[visita_cancelada] {msg}")
        record_summary(appointment_id, f"{first} {last}", email, "cancelada",
                       "Ignorado: canceled != true", "")
        return {"skipped": True, "reason": "not_canceled"}

    # ── crm.item.list — buscar visita por Acuity ID ───────────────────────────
    visita = await bitrix.find_visita_by_acuity_id(appointment_id)

    # ── FILTRO: total != 0 ────────────────────────────────────────────────────
    if not visita:
        msg = f"Visita no encontrada para appointment_id={appointment_id}"
        logger.warning(f"[visita_cancelada] {msg}")
        record_summary(appointment_id, f"{first} {last}", email, "cancelada", msg, "")
        return {"warning": msg}

    item_id       = visita.get("id")
    current_stage = visita.get("stageId", "")

    # ── FILTRO: stageId != "DT182_55:FAIL" ───────────────────────────────────
    if current_stage == config.BITRIX_STAGE_FAIL:
        msg = f"Visita ID={item_id} ya estaba en FAIL — sin cambios"
        logger.info(f"[visita_cancelada] {msg}")
        record_summary(appointment_id, f"{first} {last}", email, "cancelada", msg, str(item_id))
        return {"skipped": True, "reason": "already_FAIL", "visita_id": item_id}

    # ── crm.item.update → FAIL ────────────────────────────────────────────────
    await bitrix.update_crm_item(
        config.BITRIX_ENTITY_VISITAS, item_id,
        {"stageId": config.BITRIX_STAGE_FAIL},
    )
    logger.info(f"[visita_cancelada] Visita marcada FAIL: ID={item_id}")

    record_summary(appointment_id, f"{first} {last}", email, "cancelada",
                   f"Visita → FAIL | ID: {item_id}", str(item_id))
    return {"visita_id": item_id, "stage": config.BITRIX_STAGE_FAIL}
