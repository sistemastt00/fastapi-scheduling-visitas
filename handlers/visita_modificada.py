"""
handlers/visita_modificada.py — Blueprint 02: Visita Modificada.

Flujo exacto del blueprint (Make.com):

  Trigger: action contains "changed" AND NOT contains "canceled"
    └─ getAppointment
         └─ FILTRO: canceled == "false"
              └─ SetVariable2: fecha_iso = formatDate(addHours(datetime; -1); ...)
                   └─ FunctionSleep: 240 segundos
                        └─ crm.item.list (buscar visita por ufCrm31_1745787119410)
                             └─ FILTRO: total > 0 (visita encontrada)
                                  └─ SetVariables: visita_ant, visita_nueva
                                       └─ FILTRO: visita_ant != visita_nueva
                                                  AND title NOT contains "PRUEBA_MAKE"
                                            └─ crm.item.update (stageId, title, fechas)
"""
import asyncio
import logging

import config
from handlers.shared import (
    compute_fecha_iso, format_for_comparison, clean_notes, record_summary,
)
from services import acuity as acuity_svc
from services import bitrix

logger = logging.getLogger("scheduling-visitas")

_DELAY_SECONDS = 240  # FunctionSleep del blueprint


async def run(payload: dict) -> dict:
    appointment_id = payload.get("id")
    logger.info(f"[visita_modificada] appointment_id={appointment_id} — esperando {_DELAY_SECONDS}s")

    # ── FunctionSleep: 240 s ──────────────────────────────────────────────────
    await asyncio.sleep(_DELAY_SECONDS)

    # ── getAppointment ────────────────────────────────────────────────────────
    appt = await acuity_svc.get_appointment(appointment_id)

    # ── FILTRO: canceled == "false" (SetVariable2 del blueprint) ─────────────
    if str(appt.get("canceled", "false")).lower() == "true":
        logger.info(f"[visita_modificada] Cita {appointment_id} cancelada — ignorando")
        record_summary(appointment_id, "", "", "modificada", "Ignorado: cita cancelada", "")
        return {"skipped": True, "reason": "canceled == true"}

    # ── SetVariable2: fecha_iso ───────────────────────────────────────────────
    first    = appt.get("firstName", "")
    last     = appt.get("lastName", "")
    email    = appt.get("email", "")
    tipo     = appt.get("type", "")
    fecha_iso = compute_fecha_iso(appt.get("datetime", ""))
    title     = f"Actualizada: Visita: {first} {last} - {tipo} - {appt.get('date', '')} {appt.get('time', '')}"
    logger.info(f"[visita_modificada] {first} {last} | {tipo} | {fecha_iso}")

    # ── crm.item.list — buscar visita por Acuity ID ───────────────────────────
    visita = await bitrix.find_visita_by_acuity_id(appointment_id)

    # ── FILTRO: total > 0 ─────────────────────────────────────────────────────
    if not visita:
        msg = f"Visita no encontrada para appointment_id={appointment_id}"
        logger.warning(f"[visita_modificada] {msg}")
        record_summary(appointment_id, f"{first} {last}", email, "modificada", msg, "")
        return {"warning": msg}

    item_id = visita.get("id")

    # ── SetVariables: visita_ant vs visita_nueva ──────────────────────────────
    visita_ant   = format_for_comparison(visita.get(config.BX_FIELD_FECHA_HORA, ""))
    visita_nueva = format_for_comparison(fecha_iso)

    # ── FILTRO: visita_ant != visita_nueva AND title NOT contains "PRUEBA_MAKE" ─
    if visita_ant == visita_nueva:
        msg = f"Fecha sin cambios ({visita_ant.strip()}) — sin actualizar"
        logger.info(f"[visita_modificada] {msg}")
        record_summary(appointment_id, f"{first} {last}", email, "modificada", msg, str(item_id))
        return {"skipped": True, "reason": "same_date", "visita_id": item_id}

    if "PRUEBA_MAKE" in (visita.get("title") or ""):
        msg = "Visita marcada PRUEBA_MAKE — ignorando"
        logger.info(f"[visita_modificada] {msg}")
        record_summary(appointment_id, f"{first} {last}", email, "modificada", msg, str(item_id))
        return {"skipped": True, "reason": "PRUEBA_MAKE", "visita_id": item_id}

    # ── crm.item.update ───────────────────────────────────────────────────────
    await bitrix.update_crm_item(
        config.BITRIX_ENTITY_VISITAS, item_id,
        {
            "stageId":                      config.BITRIX_STAGE_NEW,
            "title":                        title,
            config.BX_FIELD_FECHA_HORA:     fecha_iso,
            config.BX_FIELD_FECHA_HORA_ALT: fecha_iso,
        },
    )
    logger.info(f"[visita_modificada] Visita actualizada: ID={item_id} | {visita_ant.strip()} → {visita_nueva.strip()}")

    record_summary(appointment_id, f"{first} {last}", email, "modificada",
                   f"Actualizada ID: {item_id} | {visita_ant.strip()} → {visita_nueva.strip()}",
                   str(item_id))
    return {"visita_id": item_id, "updated": True, "fecha_anterior": visita_ant.strip(), "fecha_nueva": visita_nueva.strip()}
