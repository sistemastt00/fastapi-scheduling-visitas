"""
handlers/visita_creada.py — Blueprint 01: Visita Creada.

Flujo exacto del blueprint (Make.com):

  Trigger: action contains "scheduled"
    └─ getAppointment
         └─ FILTRO: canceled == "false"
              └─ SetVariables (fecha_iso, gestor, centro, tipo_visita, notas...)
                   └─ searchContacts by EMAIL
                        └─ BasicRouter
                             ├─ [Cliente Existe E-mail] contact.ID existe
                             │    └─ searchDeals by CONTACT_ID
                             │         └─ BasicRouter anidado
                             │               ├─ [Existe Deal] deals.count > 0
                             │               │    └─ crm.item.add (con deal URL)
                             │               │         └─ crm.item.update notes (si notes != "")
                             │               └─ [No Deal] deals.count == 0
                             │                    └─ crm.item.add (sin deal URL)
                             │                         └─ crm.item.update notes (si notes != "")
                             └─ [Cliente No Existe E-mail] contact.ID no existe
                                  └─ searchContacts by PHONE
                                       └─ createAContact (si tampoco existe por teléfono)
                                            └─ crm.item.add
                                                 └─ crm.item.update notes (si notes != "")
"""
import logging

import config
from handlers.shared import (
    compute_fecha_iso, get_gestor, get_centro_revisar,
    get_tipo_visita, get_centro_formulario, clean_notes, record_summary,
)
from services import acuity as acuity_svc
from services import bitrix

logger = logging.getLogger("scheduling-visitas")


async def run(payload: dict) -> dict:
    appointment_id = payload.get("id")
    logger.info(f"[visita_creada] appointment_id={appointment_id}")

    # ── getAppointment ────────────────────────────────────────────────────────
    appt = await acuity_svc.get_appointment(appointment_id)

    # ── FILTRO: canceled == "false" (módulo 10 del blueprint) ────────────────
    if str(appt.get("canceled", "false")).lower() == "true":
        logger.info(f"[visita_creada] Cita {appointment_id} cancelada — ignorando")
        record_summary(appointment_id, "", "", "creada", "Ignorado: cita cancelada", "")
        return {"skipped": True, "reason": "canceled == true"}

    # ── SetVariables ──────────────────────────────────────────────────────────
    first    = appt.get("firstName", "")
    last     = appt.get("lastName", "")
    email    = appt.get("email", "")
    phone    = appt.get("phone", "")
    tipo     = appt.get("type", "")
    fecha_iso       = compute_fecha_iso(appt.get("datetime", ""))
    gestor_id       = get_gestor(tipo)
    centro_revisar  = get_centro_revisar(tipo)
    tipo_visita_id  = get_tipo_visita(tipo)
    centro_form_id  = get_centro_formulario(tipo)
    notes           = clean_notes(appt.get("notes", ""))

    logger.info(f"[visita_creada] {first} {last} | {tipo} | {fecha_iso}")

    # Datos de formularios Acuity
    form_names, form_values = [], []
    for form in appt.get("forms", []):
        for fv in form.get("values", []):
            form_names.append(fv.get("name", ""))
            form_values.append(fv.get("value", ""))
    form_names_str  = ", ".join(n for n in form_names  if n)
    form_values_str = ", ".join(v for v in form_values if v)

    descripcion = (
        f"Nombre: {first} {last} - "
        f"Telefonos: {phone} - "
        f"E-mail: {email} - "
        f"Tipo Visita: {form_names_str} - "
        f"Modulos a Enseñar: {form_values_str} - "
        f"Centro: {tipo}"
    )
    title       = f"Visita {first} {last} - {tipo} - {appt.get('date', '')} {appt.get('time', '')}"
    confirm_url = appt.get("confirmationPage", "")

    # ── searchContacts by EMAIL (módulo 11) ───────────────────────────────────
    contacts_email = await bitrix.search_contacts_by_email(email)

    deal_id  = None
    deal_url = ""

    # ── BasicRouter ───────────────────────────────────────────────────────────
    if contacts_email:
        # ── [Cliente Existe E-mail] contact.ID existe ─────────────────────
        contact_id = contacts_email[0]["ID"]
        logger.info(f"[visita_creada] Contacto por email: ID={contact_id}")

        # searchDeals by CONTACT_ID (módulo 17)
        deals = await bitrix.search_deals_by_contact(contact_id)

        # ── BasicRouter anidado ───────────────────────────────────────────
        if len(deals) > 0:
            # [Existe Deal] deals.count > 0
            deal_id  = deals[0]["ID"]
            deal_url = f"https://tutrasterotuotroespacio.bitrix24.eu/crm/deal/details/{deal_id}"
            logger.info(f"[visita_creada] Deal encontrado: ID={deal_id}")
        else:
            # [No Deal] deals.count == 0
            logger.info("[visita_creada] Sin deal para este contacto")

    else:
        # ── [Cliente No Existe E-mail] contact.ID no existe ───────────────
        logger.info(f"[visita_creada] Contacto no encontrado por email — buscando por teléfono")

        # searchContacts by PHONE (módulo 13)
        contacts_phone = await bitrix.search_contacts_by_phone(phone)

        # ── BasicRouter 18 ────────────────────────────────────────────────
        if contacts_phone:
            # [Cliente Existe (Phone)] — módulo 19: searchDeals by contact
            contact_id = contacts_phone[0]["ID"]
            logger.info(f"[visita_creada] Contacto por teléfono: ID={contact_id}")

            deals_phone = await bitrix.search_deals_by_contact(contact_id)

            # ── BasicRouter 20 ────────────────────────────────────────────
            if len(deals_phone) > 0:
                # [Existe Deal]
                deal_id  = deals_phone[0]["ID"]
                deal_url = f"https://tutrasterotuotroespacio.bitrix24.eu/crm/deal/details/{deal_id}"
                logger.info(f"[visita_creada] Deal encontrado (phone): ID={deal_id}")
            else:
                # [No Existe Deal]
                logger.info("[visita_creada] Sin deal para contacto por teléfono")

        else:
            # [Cliente No Existe (Phone)] — módulo 25: createAContact
            resp = await bitrix.create_contact({
                "NAME":      first,
                "LAST_NAME": last,
                "EMAIL":     [{"VALUE": email, "VALUE_TYPE": "WORK"}],
                "PHONE":     [{"VALUE": phone, "VALUE_TYPE": "WORK"}],
            })
            contact_id = resp.get("result")
            logger.info(f"[visita_creada] Contacto creado: ID={contact_id}")

    # ── crm.item.add ──────────────────────────────────────────────────────────
    fields: dict = {
        "stageId":                         config.BITRIX_STAGE_NEW,
        "title":                           title,
        "contactId":                       contact_id,
        "sourceId":                        "WEB",
        "assignedById":                    gestor_id,
        "ufCrmCreatedBy":                  gestor_id,
        config.BX_FIELD_ACUITY_ID:         str(appointment_id),
        config.BX_FIELD_FECHA_HORA:        fecha_iso,
        config.BX_FIELD_FECHA_HORA_ALT:    fecha_iso,
        config.BX_FIELD_TIPO_VISITA:       tipo_visita_id,
        config.BX_FIELD_TIPO_VISITA_ALT:   tipo,
        config.BX_FIELD_TIPO_CENTRO:       tipo,
        config.BX_FIELD_CENTRO:            centro_revisar,
        config.BX_FIELD_CENTRO_ALT:        centro_revisar,
        config.BX_FIELD_CENTRO_FORM:       centro_form_id,
        config.BX_FIELD_CATEGORIA:         config.BX_CATEGORIA_FIJA,
        config.BX_FIELD_DESCRIPCION:       descripcion,
        config.BX_FIELD_FORM_NOMBRES:      form_names_str,
        config.BX_FIELD_FORM_VALORES:      form_values_str,
        "ufCrm31_1682517684974":           "N",
        "ufCrmIsReturnCustomer":           "N",
        "ufCrmIsRepeatedApproach":         "N",
        "ufCrmClosed":                     "N",
        "isManualOpportunity":             "N",
        "ufCrm_1590739593":                "N",
        "ufCrm_1590739569":                "N",
    }

    if deal_url:
        fields[config.BX_FIELD_DEAL_URL] = deal_url
    if confirm_url:
        fields[config.BX_FIELD_CONFIRM_URL]     = confirm_url
        fields[config.BX_FIELD_CONFIRM_URL_ALT] = confirm_url

    visita_resp = await bitrix.create_crm_item(config.BITRIX_ENTITY_VISITAS, fields)
    item_id = visita_resp.get("result", {}).get("item", {}).get("id")
    logger.info(f"[visita_creada] Visita creada: ID={item_id}")

    # ── crm.item.update notes (si notes != "") ────────────────────────────────
    if notes and item_id:
        await bitrix.update_crm_item(
            config.BITRIX_ENTITY_VISITAS, item_id,
            {config.BX_FIELD_NOTAS: notes},
        )
        logger.info(f"[visita_creada] Notas actualizadas en visita ID={item_id}")

    record_summary(appointment_id, f"{first} {last}", email, "creada",
                   f"Visita ID: {item_id}", str(item_id or ""))
    return {"visita_id": item_id, "contact_id": contact_id, "deal_id": deal_id}
