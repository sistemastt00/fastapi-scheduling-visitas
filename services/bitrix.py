"""
services/bitrix.py — Cliente asíncrono para la REST API de Bitrix24.
Usa el webhook entrante configurado en BITRIX_URL.
Permisos necesarios en el webhook: CRM, Tareas, Usuarios.
"""
import httpx
import config

_TIMEOUT = 30


async def api_call(method: str, params: dict = None) -> dict:
    """Llamada genérica a la API REST de Bitrix24."""
    url = f"{config.BITRIX_URL.rstrip('/')}/{method}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(url, json=params or {})
        r.raise_for_status()
        return r.json()


# ─── Contactos ────────────────────────────────────────────────────────────────

async def search_contacts_by_email(email: str) -> list[dict]:
    """Busca contactos cuyo campo EMAIL coincida. Devuelve lista (vacía si no hay)."""
    data = await api_call("crm.contact.list", {
        "limit":  1,
        "order":  {"DATE_CREATE": "DESC"},
        "filter": {"EMAIL": email},
        "select": ["ID", "NAME", "LAST_NAME", "PHONE", "EMAIL", "ASSIGNED_BY_ID"],
    })
    return data.get("result", [])


async def create_contact(fields: dict) -> dict:
    """Crea un contacto CRM. Devuelve {result: id}."""
    return await api_call("crm.contact.add", {"fields": fields})


# ─── Deals ────────────────────────────────────────────────────────────────────

async def search_deals_by_contact(contact_id: str | int) -> list[dict]:
    """Busca deals vinculados a un contacto. Devuelve el más reciente."""
    data = await api_call("crm.deal.list", {
        "limit":  1,
        "order":  {"DATE_CREATE": "DESC"},
        "filter": {"CONTACT_ID": str(contact_id)},
        "select": ["ID", "TITLE", "CONTACT_ID"],
    })
    return data.get("result", [])


# ─── SPA Items (Entidad Visitas — type 182) ───────────────────────────────────

async def create_crm_item(entity_type_id: int, fields: dict) -> dict:
    """Crea un elemento en un pipeline SPA (crm.item.add). Devuelve el item completo."""
    return await api_call("crm.item.add", {
        "entityTypeId": entity_type_id,
        "fields":       fields,
    })


async def update_crm_item(entity_type_id: int, item_id: str | int, fields: dict) -> dict:
    """Actualiza un elemento SPA (crm.item.update)."""
    return await api_call("crm.item.update", {
        "entityTypeId": entity_type_id,
        "id":           item_id,
        "fields":       fields,
    })


async def find_visita_by_acuity_id(acuity_id: str | int) -> dict | None:
    """
    Busca una visita en la entidad SPA 182 cuyo campo de ID de Acuity coincida.
    Devuelve el primer item encontrado o None.
    """
    data = await api_call("crm.item.list", {
        "entityTypeId": config.BITRIX_ENTITY_VISITAS,
        "filter": {
            f"={config.BX_FIELD_ACUITY_ID}": str(acuity_id),
        },
        "select": ["id", "title", "stageId", config.BX_FIELD_ACUITY_ID],
    })
    items = data.get("result", {}).get("items", [])
    return items[0] if items else None
