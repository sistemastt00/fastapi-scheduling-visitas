"""
config.py — Carga variables de entorno y define constantes globales.
Único punto de verdad para IDs, rutas y parámetros del proyecto.
Los switch() son copia literal de los SetVariables del blueprint.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── Acuity Scheduling ────────────────────────────────────────────────────────
ACUITY_USER_ID        = os.getenv("ACUITY_USER_ID", "")
ACUITY_API_KEY        = os.getenv("ACUITY_API_KEY", "")
ACUITY_WEBHOOK_SECRET = os.getenv("ACUITY_WEBHOOK_SECRET", "")

# ─── Bitrix24 ─────────────────────────────────────────────────────────────────
BITRIX_URL = os.getenv("BITRIX_URL", "")

# Entidad SPA Visitas
BITRIX_ENTITY_VISITAS = 182
BITRIX_STAGE_NEW      = "DT182_55:NEW"
BITRIX_STAGE_FAIL     = "DT182_55:FAIL"

# Campos personalizados de la entidad Visitas (SPA 182)
BX_FIELD_ACUITY_ID       = "ufCrm31_1745787119410"
BX_FIELD_FECHA_HORA      = "ufCrm_1590739351"
BX_FIELD_FECHA_HORA_ALT  = "ufCrm31_1664208311266"
BX_FIELD_TIPO_VISITA     = "ufCrm31_1718778466198"
BX_FIELD_CENTRO          = "ufCrm_1608117297"
BX_FIELD_CENTRO_ALT      = "ufCrm31_1664208712198"
BX_FIELD_CENTRO_FORM     = "ufCrm_1593078333"
BX_FIELD_TIPO_CENTRO     = "ufCrm31_1710250035957"
BX_FIELD_DESCRIPCION     = "ufCrm31_1716073236196"
BX_FIELD_FORM_NOMBRES    = "ufCrm31_1716073465744"
BX_FIELD_FORM_VALORES    = "ufCrm31_1664208348434"
BX_FIELD_CONFIRM_URL     = "ufCrm31_1716073529423"
BX_FIELD_CONFIRM_URL_ALT = "ufCrm31_1716221624341"
BX_FIELD_CATEGORIA       = "ufCrm31_1716221104870"
BX_FIELD_NOTAS           = "ufCrm_1590742406"
BX_FIELD_TIPO_VISITA_ALT = "ufCrm_60523B222FBE8"
BX_FIELD_DEAL_URL        = "ufCrm31_1757428103201"

BX_CATEGORIA_FIJA = "31446"

# ─── Switch: assignedById — "Gestor segun centro" ─────────────────────────────
# switch(trim(3.type); ...) — copia literal del blueprint 01 (SetVariables)
# Búsqueda case-insensitive; default = 22435
CENTRO_GESTOR: dict[str, str] = {
    "centro sevilla":                   "76",
    "centro valladolid":                "29885",
    "centro s. s. de los reyes":        "22435",
    "centro alcobendas":                "22435",
    "centro fuencarral":                "22435",
    "centro chamartin":                 "22435",
    "centro chamartín":                 "22435",
    "centro san blas":                  "22435",
    "centro barajas":                   "22435",
    "centro móstoles":                  "22435",
    "centro mostoles":                  "22435",
    "centro leganés s. j. valderas":    "22435",
    "centro leganes s. j. valderas":    "22435",
    "centro leganés butarque":          "22435",
    "centro leganes butarque":          "22435",
    "centro alcorcón":                  "22435",
    "centro alcorcon":                  "22435",
    "centro hortaleza":                 "22435",
    "centro villaverde":                "22435",
    "porte":                            "22435",
}
DEFAULT_GESTOR_ID: str = "22435"

# ─── Switch: "Centro a Revisar" → ufCrm_1608117297 ───────────────────────────
# switch(lower(trim(3.type)); ...) — copia literal del blueprint 01 (SetVariables)
CENTRO_REVISAR: dict[str, str] = {
    "centro s. s. de los reyes":        "24395",
    "centro sevilla":                   "24399",
    "centro fuencarral":                "24387",
    "centro chamartin":                 "24385",
    "centro chamartín":                 "24385",
    "centro san blas":                  "24397",
    "centro barajas":                   "24383",
    "centro móstoles":                  "24393",
    "centro mostoles":                  "24393",
    "centro leganés s. j. valderas":    "24391",
    "centro leganes s. j. valderas":    "24391",
    "centro leganés butarque":          "24389",
    "centro leganes butarque":          "24389",
    "centro alcorcón":                  "24381",
    "centro alcorcon":                  "24381",
    "centro valladolid":                "30116",
    "centro hortaleza":                 "31444",
    "centro villaverde":                "31660",
}
DEFAULT_CENTRO_REVISAR: str = "24379"

# ─── Switch: "Tipo Visita" → ufCrm31_1718778466198 ───────────────────────────
# switch(lower(trim(3.type)); ...) — copia literal del blueprint 01 (SetVariables)
TIPO_VISITA_IDS: dict[str, str] = {
    "comercial":              "31480",
    "primera visita":         "31482",
    "virtual comercial":      "31484",
    "virtual primera visita": "31486",
    "porte":                  "31488",
}
DEFAULT_TIPO_VISITA: str = "31480"

# ─── Switch: "Centro Formulario" → ufCrm_1593078333 ──────────────────────────
# switch(lower(trim(3.type)); ...) — copia literal del blueprint 01 (SetVariables)
CENTRO_FORMULARIO: dict[str, str] = {
    "centro s. s. de los reyes":        "24591",
    "centro sevilla":                   "24595",
    "centro fuencarral":                "24581",
    "centro chamartin":                 "24579",
    "centro chamartín":                 "24579",
    "centro san blas":                  "24593",
    "centro barajas":                   "24577",
    "centro móstoles":                  "24587",
    "centro mostoles":                  "24587",
    "centro leganés s. j. valderas":    "24585",
    "centro leganes s. j. valderas":    "24585",
    "centro leganés butarque":          "24583",
    "centro leganes butarque":          "24583",
    "centro alcorcón":                  "24575",
    "centro alcorcon":                  "24575",
    "centro valladolid":                "24597",
    "centro hortaleza":                 "31442",
    "centro villaverde":                "31662",
}
DEFAULT_CENTRO_FORMULARIO: str = "24573"

# ─── Deploy webhook ───────────────────────────────────────────────────────────
DEPLOY_TOKEN = os.getenv("DEPLOY_TOKEN", "")
DEPLOY_DIR   = os.getenv("DEPLOY_DIR", "/opt/fastapi-scheduling-visitas")

# ─── Telegram — alertas de error ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
