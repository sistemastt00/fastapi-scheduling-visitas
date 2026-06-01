"""
services/airtable.py — Registro de visitas en Airtable.
Upsert usando acuity_id como clave única.
Nunca lanza excepción: errores se loggean y el flujo continúa.
"""
import logging

import httpx

import config

logger = logging.getLogger("scheduling-visitas")


async def upsert_visita(acuity_id: str, cliente: str, email: str, bitrix_182_id: str, accion: str = "") -> str | None:
    """
    Crea o actualiza un registro en Airtable con los datos de la visita.
    Devuelve el record_id o None si falla.
    """
    if not config.AIRTABLE_TOKEN:
        logger.warning("Airtable: AIRTABLE_TOKEN no configurado — se omite grabación")
        return None

    headers = {
        "Authorization": f"Bearer {config.AIRTABLE_TOKEN}",
        "Content-Type":  "application/json",
    }
    base_url = f"https://api.airtable.com/v0/{config.AIRTABLE_BASE_ID}/{config.AIRTABLE_TABLE_ID}"
    log_key  = f"acuity_id='{acuity_id}'"

    campos = {
        "acuity_id":     acuity_id,
        "cliente":       cliente,
        "email":         email,
        "bitrix_182_id": bitrix_182_id,
        "accion":        accion,
    }
    campos = {k: v for k, v in campos.items() if v is not None and v != ""}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                base_url,
                headers=headers,
                params={"filterByFormula": f"{{acuity_id}}='{acuity_id}'"},
            )
            if r.status_code != 200:
                logger.error(f"Airtable: error buscando {log_key} — {r.status_code} {r.text[:200]}")
                return None

            registros = r.json().get("records", [])

            if registros:
                record_id = registros[0]["id"]
                r2 = await client.patch(
                    f"{base_url}/{record_id}",
                    headers=headers,
                    json={"fields": campos},
                )
                if r2.status_code == 200:
                    logger.info(f"Airtable: actualizado {log_key} (record {record_id})")
                    return record_id
                else:
                    logger.error(f"Airtable: error actualizando {log_key} — {r2.status_code} {r2.text[:200]}")
                    return None
            else:
                r2 = await client.post(
                    base_url,
                    headers=headers,
                    json={"records": [{"fields": campos}]},
                )
                if r2.status_code in (200, 201):
                    record_id = r2.json().get("records", [{}])[0].get("id")
                    logger.info(f"Airtable: creado {log_key} (record {record_id})")
                    return record_id
                else:
                    logger.error(f"Airtable: error creando {log_key} — {r2.status_code} {r2.text[:200]}")
                    return None

    except httpx.TimeoutException:
        logger.error(f"Airtable: timeout en upsert {log_key}")
        return None
    except Exception as e:
        logger.error(f"Airtable: excepción en upsert {log_key} — {type(e).__name__}: {e}")
        return None
