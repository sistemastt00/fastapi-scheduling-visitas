"""
handlers/shared.py — Funciones compartidas entre handlers.
Replica las operaciones de util:SetVariables / util:SetVariable2 del blueprint.
"""
import re
import datetime as dt_mod

import config


# ─── fecha_iso ────────────────────────────────────────────────────────────────

def compute_fecha_iso(dt_str: str) -> str:
    """
    Replica: formatDate(addHours(datetime; -1); "YYYY-MM-DDTHH:mm:ssZ"; "Europe/Madrid")
    → Resta 1 hora al datetime de Acuity y devuelve ISO 8601 con offset.
    El -1h es el ajuste que Make.com aplica internamente por su manejo de timezones.
    """
    if not dt_str:
        return ""
    try:
        normalized = re.sub(r"([+-])(\d{2})(\d{2})$", r"\1\2:\3", dt_str)
        parsed = dt_mod.datetime.fromisoformat(normalized)
        result = parsed - dt_mod.timedelta(hours=1)
        return result.isoformat()
    except Exception:
        return dt_str


def format_for_comparison(dt_str: str) -> str:
    """
    Replica: formatDate(fecha; " DD.MM.YYYY HH:mm "; "UTC")
    → Usado para comparar visita_ant vs visita_nueva en blueprint 02.
    """
    if not dt_str:
        return ""
    try:
        normalized = re.sub(r"([+-])(\d{2})(\d{2})$", r"\1\2:\3", dt_str)
        parsed = dt_mod.datetime.fromisoformat(normalized)
        parsed_utc = parsed.astimezone(dt_mod.timezone.utc)
        return parsed_utc.strftime(" %d.%m.%Y %H:%M ")
    except Exception:
        return dt_str


# ─── Switch tables (SetVariables) ─────────────────────────────────────────────

def get_gestor(tipo: str) -> str:
    """switch(trim(3.type); ...) → assignedById"""
    return config.CENTRO_GESTOR.get(tipo.strip().lower(), config.DEFAULT_GESTOR_ID)


def get_centro_revisar(tipo: str) -> str:
    """switch(lower(trim(3.type)); ...) → ufCrm_1608117297"""
    return config.CENTRO_REVISAR.get(tipo.strip().lower(), config.DEFAULT_CENTRO_REVISAR)


def get_tipo_visita(tipo: str) -> str:
    """switch(lower(trim(3.type)); ...) → ufCrm31_1718778466198"""
    return config.TIPO_VISITA_IDS.get(tipo.strip().lower(), config.DEFAULT_TIPO_VISITA)


def get_centro_formulario(tipo: str) -> str:
    """switch(lower(trim(3.type)); ...) → ufCrm_1593078333"""
    return config.CENTRO_FORMULARIO.get(tipo.strip().lower(), config.DEFAULT_CENTRO_FORMULARIO)


# ─── Limpieza de notes ────────────────────────────────────────────────────────

def clean_notes(notes: str) -> str:
    """
    Replica: toString(trim(replace(replace(replace(replace(notes; newline; space); ...)))))
    → Elimina saltos de línea, comillas problemáticas y espacios múltiples.
    """
    if not notes:
        return ""
    notes = notes.replace("\n", " ").replace("\r", " ")
    notes = notes.replace('"', "").replace("'", "")
    notes = re.sub(r"\s{2,}", " ", notes).strip()
    return notes


# ─── Monitor summary helper ───────────────────────────────────────────────────

def record_summary(appt_id, client: str, email: str, action: str,
                   result: str, bitrix_id: str) -> None:
    import state
    state.summaries.appendleft({
        "time":           dt_mod.datetime.now().strftime("%d/%m %H:%M:%S"),
        "appointment_id": str(appt_id),
        "client":         client,
        "email":          email,
        "action":         action,
        "result":         result,
        "bitrix_id":      bitrix_id,
    })
