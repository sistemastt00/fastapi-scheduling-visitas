"""
config.py — Carga variables de entorno y define constantes globales.
Único punto de verdad para IDs, rutas y parámetros del proyecto.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── Acuity Scheduling ────────────────────────────────────────────────────────
ACUITY_USER_ID        = os.getenv("ACUITY_USER_ID", "")
ACUITY_API_KEY        = os.getenv("ACUITY_API_KEY", "")
ACUITY_WEBHOOK_SECRET = os.getenv("ACUITY_WEBHOOK_SECRET", "")  # HMAC-SHA256

# ─── Bitrix24 ─────────────────────────────────────────────────────────────────
BITRIX_URL = os.getenv("BITRIX_URL", "")   # https://tutrastero.bitrix24.eu/rest/ID/TOKEN

# Entidad SPA Visitas
BITRIX_ENTITY_VISITAS = 182
BITRIX_STAGE_NEW      = "DT182_55:NEW"
BITRIX_STAGE_FAIL     = "DT182_55:FAIL"

# Campos personalizados de la entidad Visitas (SPA 182)
BX_FIELD_ACUITY_ID       = "ufCrm31_1745787119410"   # ID de la cita en Acuity (clave de búsqueda)
BX_FIELD_FECHA_HORA      = "ufCrm_1590739351"          # Fecha y hora ISO de la visita
BX_FIELD_FECHA_HORA_ALT  = "ufCrm31_1664208311266"     # Fecha y hora ISO (campo alternativo)
BX_FIELD_TIPO_VISITA     = "ufCrm31_1718778466198"     # Tipo de visita (del tipo de cita Acuity)
BX_FIELD_CENTRO          = "ufCrm_1608117297"          # Centro a revisar
BX_FIELD_CENTRO_ALT      = "ufCrm31_1664208712198"     # Centro (campo alternativo)
BX_FIELD_CENTRO_FORM     = "ufCrm_1593078333"          # Centro formulario
BX_FIELD_TIPO_CENTRO     = "ufCrm31_1710250035957"     # Tipo/centro del appointment
BX_FIELD_DESCRIPCION     = "ufCrm31_1716073236196"     # Descripción completa del cliente
BX_FIELD_FORM_NOMBRES    = "ufCrm31_1716073465744"     # Nombres de campos del formulario
BX_FIELD_FORM_VALORES    = "ufCrm31_1664208348434"     # Valores de campos del formulario
BX_FIELD_CONFIRM_URL     = "ufCrm31_1716073529423"     # URL de confirmación de cita
BX_FIELD_CONFIRM_URL_ALT = "ufCrm31_1716221624341"     # URL de confirmación (alternativo)
BX_FIELD_CATEGORIA       = "ufCrm31_1716221104870"     # Categoría fija ("31446")
BX_FIELD_NOTAS           = "ufCrm_1590742406"          # Notas / comentarios
BX_FIELD_TIPO_VISITA_ALT = "ufCrm_60523B222FBE8"       # Tipo de visita (alternativo)
BX_FIELD_DEAL_URL        = "ufCrm31_1757428103201"     # URL del deal relacionado

# Valor fijo de categoría (constante del negocio)
BX_CATEGORIA_FIJA = "31446"

# ─── Mapas configurables: tipo de cita Acuity → valores Bitrix24 ─────────────
# Fuente: GET /api/v1/appointment-types (36312399)
# Rellenar los valores (strings vacíos = campo no se envía a Bitrix24)

# Clave: nombre exacto del tipo de cita | Valor: ID de usuario Bitrix24 del gestor
CENTRO_GESTOR: dict[str, str] = {
    "Centro S. S. de los Reyes":      "",
    "Centro Alcobendas":              "",
    "Centro Fuencarral":              "",
    "Centro Chamartín":               "",
    "Centro San Blas":                "",
    "Centro Barajas":                 "",
    "Centro Móstoles":                "",
    "Centro Leganés S. J. Valderas":  "",
    "Centro Leganés Butarque":        "",
    "Centro Alcorcón":                "",
    "Centro Sevilla":                 "",
    "Centro Valladolid":              "",
    "Centro Hortaleza":               "",
    "Centro Villaverde":              "",
    "Porte":                          "",
}

# Clave: nombre exacto del tipo de cita | Valor: valor del campo centro en Bitrix24
CENTRO_BITRIX: dict[str, str] = {
    "Centro S. S. de los Reyes":      "",
    "Centro Alcobendas":              "",
    "Centro Fuencarral":              "",
    "Centro Chamartín":               "",
    "Centro San Blas":                "",
    "Centro Barajas":                 "",
    "Centro Móstoles":                "",
    "Centro Leganés S. J. Valderas":  "",
    "Centro Leganés Butarque":        "",
    "Centro Alcorcón":                "",
    "Centro Sevilla":                 "",
    "Centro Valladolid":              "",
    "Centro Hortaleza":               "",
    "Centro Villaverde":              "",
    "Porte":                          "",
}

# ID del gestor por defecto si el tipo de cita no está en el mapa
DEFAULT_GESTOR_ID: str = ""

# ─── Deploy webhook ───────────────────────────────────────────────────────────
DEPLOY_TOKEN = os.getenv("DEPLOY_TOKEN", "")
DEPLOY_DIR   = os.getenv("DEPLOY_DIR", "/opt/fastapi-scheduling-visitas")

# ─── Telegram — alertas de error ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
