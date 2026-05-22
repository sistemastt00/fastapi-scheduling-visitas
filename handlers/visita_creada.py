"""
handlers/visita_creada.py — Lógica para citas nuevas (blueprint 01).
Flujo: buscar/crear contacto → buscar deal → crear visita en Bitrix24.
"""
import datetime
import logging
import re

import config
import state
from services import acuity as acuity_svc
from services import bitrix

logger = logging.getLogger("scheduling-visitas")


def _format_datetime(dt_str: str) -> str:
    """Normaliza el datetime de Acuity a ISO 8601 con separador de offset (±HH:MM)."""
    if not dt_str:
        return ""
    # Acuity puede dar -0500; convertir a -05:00
    return re.sub(r"([+-])(\d{2})(\d{2})$", r"\1\2:\3", dt_str)


async def run(payload: dict) -> dict:
    """
    payload: datos del webhook de Acuity (acción 'appointment.scheduled').
    Retorna resumen con visita_id, contact_id, deal_id.
    """
    appointment_id = payload.get("id")
    logger.info(f"[visita_creada] appointment_id={appointment_id}")

    # 1. Detalles completos de la cita
    appt = await acuity_svc.get_appointment(appointment_id)
    first    = appt.get("firstName", "")
    last     = appt.get("lastName", "")
    email    = appt.get("email", "")
    phone    = appt.get("phone", "")
    tipo     = appt.get("type", "")
    fecha_dt = _format_datetime(appt.get("datetime", ""))
    logger.info(f"[visita_creada] {first} {last} | {tipo} | {fecha_dt}")

    # 2. Buscar o crear contacto por email
    contacts = await bitrix.search_contacts_by_email(email)
    if contacts:
        contact_id = contacts[0]["ID"]
        logger.info(f"[visita_creada] Contacto encontrado: ID={contact_id}")
    else:
        resp = await bitrix.create_contact({
            "NAME":      first,
            "LAST_NAME": last,
            "EMAIL":     [{"VALUE": email, "VALUE_TYPE": "WORK"}],
            "PHONE":     [{"VALUE": phone, "VALUE_TYPE": "WORK"}],
        })
        contact_id = resp.get("result")
        logger.info(f"[visita_creada] Contacto creado: ID={contact_id}")

    # 3. Buscar deal más reciente del contacto
    deal_id   = None
    deal_url  = ""
    deals = await bitrix.search_deals_by_contact(contact_id)
    if deals:
        deal_id  = deals[0]["ID"]
        deal_url = f"https://tutrasterotuotroespacio.bitrix24.eu/crm/deal/details/{deal_id}"
        logger.info(f"[visita_creada] Deal encontrado: ID={deal_id}")

    # 4. Resolver gestor y centro según tipo de cita
    gestor_id    = config.CENTRO_GESTOR.get(tipo, config.DEFAULT_GESTOR_ID)
    centro_bx    = config.CENTRO_BITRIX.get(tipo, "")

    # 5. Datos de formularios de Acuity
    form_names  = []
    form_values = []
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
    title = f"Visita {first} {last} - {tipo} - {appt.get('date', '')} {appt.get('time', '')}"
    confirm_url = appt.get("confirmationPage", "")

    # 6. Campos de la visita
    fields: dict = {
        "stageId":                         config.BITRIX_STAGE_NEW,
        "title":                           title,
        "contactId":                       contact_id,
        "sourceId":                        "WEB",
        config.BX_FIELD_ACUITY_ID:         str(appointment_id),
        config.BX_FIELD_FECHA_HORA:        fecha_dt,
        config.BX_FIELD_FECHA_HORA_ALT:    fecha_dt,
        config.BX_FIELD_TIPO_VISITA:       tipo,
        config.BX_FIELD_TIPO_VISITA_ALT:   tipo,
        config.BX_FIELD_TIPO_CENTRO:       tipo,
        config.BX_FIELD_DESCRIPCION:       descripcion,
        config.BX_FIELD_FORM_NOMBRES:      form_names_str,
        config.BX_FIELD_FORM_VALORES:      form_values_str,
        config.BX_FIELD_CATEGORIA:         config.BX_CATEGORIA_FIJA,
        "ufCrm31_1682517684974":           "N",
        "ufCrmIsReturnCustomer":           "N",
        "ufCrmIsRepeatedApproach":         "N",
        "ufCrmClosed":                     "N",
        "isManualOpportunity":             "N",
        "ufCrm_1590739593":                "N",
        "ufCrm_1590739569":                "N",
    }

    if gestor_id:
        fields["assignedById"]      = gestor_id
        fields["ufCrmCreatedBy"]    = gestor_id
        fields["ufCrmCreatedById"]  = gestor_id
    if centro_bx:
        fields[config.BX_FIELD_CENTRO]     = centro_bx
        fields[config.BX_FIELD_CENTRO_ALT] = centro_bx
        fields[config.BX_FIELD_CENTRO_FORM] = centro_bx
    if deal_url:
        fields[config.BX_FIELD_DEAL_URL] = deal_url
    if confirm_url:
        fields[config.BX_FIELD_CONFIRM_URL]     = confirm_url
        fields[config.BX_FIELD_CONFIRM_URL_ALT] = confirm_url

    # 7. Crear visita
    visita_resp = await bitrix.create_crm_item(config.BITRIX_ENTITY_VISITAS, fields)
    item_id = visita_resp.get("result", {}).get("item", {}).get("id")
    logger.info(f"[visita_creada] Visita creada: ID={item_id}")

    # 8. Actualizar notas si existen
    notes = appt.get("notes", "")
    if notes and item_id:
        await bitrix.update_crm_item(
            config.BITRIX_ENTITY_VISITAS, item_id,
            {config.BX_FIELD_NOTAS: notes},
        )

    # Registrar en el monitor
    _record_summary(appointment_id, f"{first} {last}", email, "creada",
                    f"Visita ID: {item_id}", str(item_id or ""))
    return {"visita_id": item_id, "contact_id": contact_id, "deal_id": deal_id}


def _record_summary(appt_id, client, email, action, result, bitrix_id):
    import datetime
    state.summaries.appendleft({
        "time":           datetime.datetime.now().strftime("%d/%m %H:%M:%S"),
        "appointment_id": str(appt_id),
        "client":         client,
        "email":          email,
        "action":         action,
        "result":         result,
        "bitrix_id":      bitrix_id,
    })
