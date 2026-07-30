"""
main.py — Scheduling Visitas Bot
FastAPI + Acuity Scheduling + Bitrix24 + Telegram

Arquitectura:
  · Webhook POST /acuity : recibe eventos de Acuity (scheduled / rescheduled / canceled)
  · Deploy   POST /deploy: git pull + reinicio del servicio
  · Monitor  GET  /monitor: panel de logs en tiempo real
"""
import asyncio
import contextvars
import datetime
import json
import logging
import os
import signal
import subprocess
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Cookie, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
import bcrypt as _bcrypt, secrets as _secrets, time as _time, base64 as _base64
from typing import Optional
from pathlib import Path as _Path

# ─── Auth compartida con Monitor Global ──────────────────────
_AUTH_USERS_FILE = _Path("/opt/fastapi-monitor-global/users.json")
_AUTH_SESSIONS: dict = {}
_AUTH_ATTEMPTS: dict = {}
_AUTH_MAX, _AUTH_WIN = 5, 600
_AUTH_LOGO_URL = ""
try:
    _lp = _Path("/opt/fastapi-monitor-global/logo.png")
    if _lp.exists():
        _AUTH_LOGO_URL = "data:image/png;base64," + _base64.b64encode(_lp.read_bytes()).decode()
except Exception:
    pass
_AUTH_MONITOR_NAME = "Scheduling Visitas"

def _auth_load() -> dict:
    if _AUTH_USERS_FILE.exists():
        try: return json.loads(_AUTH_USERS_FILE.read_text(encoding="utf-8"))
        except Exception: pass
    return {}

def _auth_ok(session) -> bool:
    return bool(session and session in _AUTH_SESSIONS)

def _auth_page(err: str = "") -> str:
    if err == "2":
        err_html = '<div class="error">🔒 Demasiados intentos. Espera 10 minutos.</div>'
    elif err:
        err_html = '<div class="error">⚠ Usuario o contraseña incorrectos</div>'
    else:
        err_html = ""
    logo_html = f'<img src="{_AUTH_LOGO_URL}" alt="Tu Trastero">' if _AUTH_LOGO_URL else ""
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_AUTH_MONITOR_NAME} — Acceso</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:#F1F5F9;--su:#fff;--t1:#0F172A;--t2:#475569;--t3:#64748B;--bo:#E2E8F0;--grn:#059669;--rs:8px}}
@media(prefers-color-scheme:dark){{:root{{--bg:#0F172A;--su:#1E293B;--t1:#F1F5F9;--t2:#94A3B8;--t3:#64748B;--bo:#334155}}}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;background:var(--bg);display:flex;align-items:center;justify-content:center;min-height:100vh}}
.box{{background:var(--su);border-radius:12px;padding:44px 40px;width:380px;box-shadow:0 1px 3px rgba(0,0,0,.06),0 4px 20px rgba(0,0,0,.06);border:1px solid var(--bo)}}
.logo-area{{text-align:center;margin-bottom:32px}}
.logo-area img{{height:42px;max-width:100%;object-fit:contain;margin-bottom:12px;display:block;margin-left:auto;margin-right:auto}}
h2{{color:var(--t1);font-size:.95em;text-align:center;letter-spacing:1px;text-transform:uppercase;font-weight:700}}
.sub{{color:var(--t3);font-size:.75em;text-align:center;margin-top:4px}}
.error{{background:#FEF2F2;border:1px solid rgba(220,38,38,.25);color:#DC2626;padding:9px 14px;border-radius:var(--rs);font-size:.82em;margin:18px 0 0;text-align:center}}
.field{{margin-top:18px}}
label{{display:block;color:var(--t2);font-size:.75em;letter-spacing:.5px;text-transform:uppercase;margin-bottom:5px;font-weight:600}}
input{{width:100%;background:var(--su);border:1px solid var(--bo);color:var(--t1);padding:10px 14px;border-radius:var(--rs);font-family:inherit;font-size:.95em;outline:none;transition:border-color .15s,box-shadow .15s}}
input:focus{{border-color:var(--grn);box-shadow:0 0 0 3px rgba(5,150,105,.12)}}
.btn{{width:100%;background:var(--t1);border:none;color:#fff;padding:12px;border-radius:var(--rs);font-family:inherit;font-size:.9em;font-weight:600;cursor:pointer;letter-spacing:.05em;text-transform:uppercase;margin-top:24px;transition:opacity .15s}}
.btn:hover{{opacity:.85}}
</style>
</head>
<body>
<div class="box">
  <div class="logo-area">
    {logo_html}
    <h2>{_AUTH_MONITOR_NAME}</h2>
    <div class="sub">FastAPI · tutrastero.com</div>
  </div>
  {err_html}
  <form method="post" action="/login">
    <div class="field"><label>Usuario</label>
      <input type="email" name="username" placeholder="usuario@dominio.com" autofocus required></div>
    <div class="field"><label>Contraseña</label>
      <input type="password" name="password" placeholder="········" required></div>
    <button type="submit" class="btn">Acceder</button>
  </form>
</div>
</body></html>"""

import config
import state
from services import telegram as telegram_svc
from services import acuity   as acuity_svc
from handlers import visita_creada, visita_modificada, visita_cancelada

# ─── Logging ──────────────────────────────────────────────────────────────────

_LOG_FILE = Path(__file__).parent / "logs.txt"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        RotatingFileHandler(_LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("scheduling-visitas")

# ContextVar: appointment_id activo durante la ejecución de un handler
_current_appt_id: contextvars.ContextVar[str] = contextvars.ContextVar("appt_id", default="")


class _MonitorHandler(logging.Handler):
    def emit(self, record):
        state.history.append({
            "time":    datetime.datetime.fromtimestamp(record.created).strftime("%d/%m %H:%M:%S"),
            "level":   record.levelname,
            "message": self.format(record),
            "appt_id": _current_appt_id.get(""),
        })
        state.save()


_mh = _MonitorHandler()
_mh.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_mh)

# ─── Dispatcher de acciones ───────────────────────────────────────────────────

_ACTIONS = {
    "scheduled":    visita_creada.run,
    "rescheduled":  visita_modificada.run,
    "canceled":     visita_cancelada.run,
}

# ─── App ──────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    state.load()
    await telegram_svc.send_alert("✅ *Scheduling Visitas* — servicio iniciado")
    logger.info("🗓️  Scheduling Visitas iniciado — esperando webhooks de Acuity")
    yield
    await telegram_svc.send_alert("🔴 *Scheduling Visitas* — servicio detenido")


app = FastAPI(title="Scheduling Visitas Bot", lifespan=lifespan)

# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "status":  "ok",
        "bot":     "scheduling-visitas",
        "actions": list(_ACTIONS),
    }


@app.post("/acuity")
async def acuity_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Recibe webhooks de Acuity Scheduling.
    Payload form-encoded: action, id, calendarID, appointmentTypeID.
    """
    raw_body = await request.body()

    # Verificar firma HMAC si ACUITY_WEBHOOK_SECRET está configurado
    sig = request.headers.get("X-Acuity-Signature", "")
    if not acuity_svc.verify_signature(raw_body, sig):
        logger.warning("Webhook rechazado: firma inválida")
        raise HTTPException(status_code=403, detail="Firma inválida")

    # Parsear payload (form-encoded o JSON)
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
    else:
        form = await request.form()
        payload = dict(form)

    action         = payload.get("action", "")
    appointment_id = payload.get("id", "")
    logger.info(f"Acuity webhook | action={action} | appointment_id={appointment_id}")

    handler = _ACTIONS.get(action)
    if handler is None:
        logger.warning(f"Acción desconocida: {action!r}")
        return JSONResponse(
            status_code=400,
            content={"error": f"Acción desconocida: {action}", "disponibles": list(_ACTIONS)},
        )

    # Procesar en background para devolver 200 inmediatamente a Acuity
    background_tasks.add_task(_run_handler, handler, payload, action)
    return {"status": "ok", "action": action}


async def _run_handler(handler, payload: dict, action: str):
    # Inyectar appointment_id en el contexto para que todos los logs queden etiquetados
    token = _current_appt_id.set(str(payload.get("id", "")))
    try:
        result = await handler(payload)
        logger.info(f"[{action}] OK → {json.dumps(result, ensure_ascii=False)[:300]}")
        state.stats[action] = state.stats.get(action, 0) + 1
    except Exception as exc:
        logger.error(f"[{action}] Error: {exc}", exc_info=True)
        state.stats["errors"] = state.stats.get("errors", 0) + 1
        await telegram_svc.send_alert(
            f"⚠️ *Scheduling Visitas* — error en `{action}`\n"
            f"❌ `{type(exc).__name__}: {str(exc)[:200]}`"
        )
    finally:
        _current_appt_id.reset(token)


@app.get("/api/stats")
def api_stats():
    """Estadísticas de visitas para el Monitor Global."""
    return {
        "counters": dict(state.stats),
        "total":    state.stats.get("scheduled", 0) + state.stats.get("rescheduled", 0) + state.stats.get("canceled", 0),
        "history":  len(state.history),
    }


@app.post("/deploy")
async def deploy(request: Request, background_tasks: BackgroundTasks):
    """Git pull + reinicio del servicio vía SIGTERM (systemd lo relanza)."""
    token = request.query_params.get("token", "")
    if not config.DEPLOY_TOKEN or token != config.DEPLOY_TOKEN:
        raise HTTPException(status_code=403, detail="Token inválido")

    if not config.DEPLOY_DIR:
        raise HTTPException(status_code=500, detail="DEPLOY_DIR no configurado")

    result = subprocess.run(
        ["git", "-C", config.DEPLOY_DIR, "pull"],
        capture_output=True, text=True, timeout=30,
    )
    output = (result.stdout + result.stderr).strip()
    logger.info(f"[deploy] git pull → {output}")

    background_tasks.add_task(_restart_after_delay)
    return {"status": "ok", "git": output}


async def _restart_after_delay():
    await asyncio.sleep(1)
    logger.info("[deploy] Reiniciando proceso para aplicar cambios…")
    os.kill(os.getpid(), signal.SIGTERM)


@app.get("/login", response_class=HTMLResponse)
def _login_page(error: str = ""):
    return _auth_page(error)


@app.post("/login")
async def _login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    ip = request.client.host if request.client else "unknown"
    now = _time.time()
    attempts = [t for t in _AUTH_ATTEMPTS.get(ip, []) if now - t < _AUTH_WIN]
    if len(attempts) >= _AUTH_MAX:
        _AUTH_ATTEMPTS[ip] = attempts
        return RedirectResponse("/login?error=2", status_code=302)
    users = _auth_load()
    h = users.get(username)
    ok = False
    if h:
        try: ok = _bcrypt.checkpw(password.encode(), h.encode())
        except Exception: pass
    if ok:
        _AUTH_ATTEMPTS.pop(ip, None)
        token = _secrets.token_hex(32)
        _AUTH_SESSIONS[token] = username
        resp = RedirectResponse("/monitor", status_code=302)
        resp.set_cookie("session", token, httponly=True, samesite="lax", max_age=86400)
        return resp
    attempts.append(now)
    _AUTH_ATTEMPTS[ip] = attempts
    return RedirectResponse("/login?error=1" if len(attempts) < _AUTH_MAX else "/login?error=2", status_code=302)


@app.get("/logout")
def _logout(session: Optional[str] = Cookie(default=None)):
    _AUTH_SESSIONS.pop(session or "", None)
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("session")
    return resp


@app.get("/monitor", response_class=HTMLResponse)
async def monitor(session: Optional[str] = Cookie(default=None)):
    if not _auth_ok(session):
        return RedirectResponse("/login", status_code=302)
    return _render_monitor()


# ─── Monitor HTML ─────────────────────────────────────────────────────────────

def _build_flow_path(msgs_text: str, action: str) -> list:
    """
    Parsea los mensajes de log de una cita y devuelve una lista de pasos
    del flujo que tomó: [{label, icon, color, dim}]
    dim=True = paso no ejecutado / rama no tomada (gris).
    """
    m = msgs_text  # texto completo para búsquedas rápidas
    steps = []

    def step(icon, label, color="#3498db", dim=False):
        steps.append({"icon": icon, "label": label, "color": color, "dim": dim})

    if action == "creada":
        step("⚡", "Webhook", "#3498db")
        step("🔌", "getAppointment", "#666")

        if "cita cancelada" in m.lower():
            step("⛔", "canceled=true → skip", "#555", dim=True)
            return steps

        step("✓", "canceled=false", "#2ecc71")
        step("📐", "SetVariables", "#9b59b6")

        # Búsqueda por email
        if "Contacto por email:" in m:
            step("📧", "Email encontrado", "#2ecc71")
            if "Deal encontrado:" in m:
                step("💼", "Deal encontrado", "#2ecc71")
            else:
                step("💼", "Sin deal", "#e67e22")
        else:
            step("📧", "Sin contacto email", "#e74c3c")
            if "Contacto por teléfono:" in m:
                step("📱", "Tel. encontrado", "#2ecc71")
                if "Deal encontrado (phone):" in m:
                    step("💼", "Deal encontrado", "#2ecc71")
                else:
                    step("💼", "Sin deal", "#e67e22")
            elif "Contacto creado:" in m:
                step("👤", "Contacto creado", "#9b59b6")

        if "Visita creada:" in m:
            step("✅", "crm.item.add", "#2ecc71")
        if "Notas actualizadas" in m:
            step("📝", "Notas", "#3498db")

    elif action == "modificada":
        step("⚡", "Webhook", "#3498db")
        step("🔌", "getAppointment", "#666")

        if "cancelada — ignorando" in m:
            step("⛔", "canceled=true → skip", "#555", dim=True)
            return steps

        step("✓", "canceled=false", "#2ecc71")
        step("📐", "fecha_iso −1h", "#9b59b6")
        step("⏳", "Sleep 60s", "#e67e22")
        step("🔍", "crm.item.list", "#666")

        if "no encontrada" in m.lower():
            step("⚠️", "Visita no encontrada", "#e74c3c", dim=True)
            return steps

        if "Fecha sin cambios" in m:
            step("⏸", "Fecha sin cambio → skip", "#555", dim=True)
            return steps
        if "PRUEBA_MAKE" in m:
            step("🧪", "PRUEBA_MAKE → skip", "#555", dim=True)
            return steps

        step("🔀", "Fecha cambió", "#2ecc71")
        step("✅", "crm.item.update", "#f39c12")

    elif action == "cancelada":
        step("⚡", "Webhook", "#3498db")
        step("🔌", "getAppointment", "#666")

        if "no está cancelada" in m:
            step("⛔", "canceled=false → skip", "#555", dim=True)
            return steps

        step("✓", "canceled=true", "#e74c3c")
        step("🔍", "crm.item.list", "#666")

        if "no encontrada" in m.lower():
            step("⚠️", "Visita no encontrada", "#e74c3c", dim=True)
            return steps
        if "ya estaba en FAIL" in m:
            step("⏸", "Ya en FAIL → skip", "#555", dim=True)
            return steps

        step("❌", "→ FAIL", "#e74c3c")

    return steps


def _render_flow_path(steps: list) -> str:
    if not steps:
        return ""
    pills = ""
    for i, s in enumerate(steps):
        opacity  = "0.35" if s.get("dim") else "1"
        bg       = "#0d0d1e"
        border   = s["color"] if not s.get("dim") else "#222"
        color    = s["color"] if not s.get("dim") else "#444"
        pills += (
            f'<span style="display:inline-flex;align-items:center;gap:4px;'
            f'background:{bg};border:1px solid {border};color:{color};'
            f'padding:2px 9px;border-radius:12px;font-size:.7em;opacity:{opacity};white-space:nowrap">'
            f'{s["icon"]} {s["label"]}</span>'
        )
        if i < len(steps) - 1:
            pills += '<span style="color:#222;font-size:.75em;padding:0 1px">→</span>'
    return (
        f'<div style="display:flex;align-items:center;flex-wrap:wrap;gap:4px;'
        f'padding:7px 14px;background:#07070f;border-bottom:1px solid #111128">'
        f'<span style="color:#333;font-size:.68em;margin-right:4px">FLUJO</span>'
        f'{pills}</div>'
    )


# Palabras clave que marcan una línea de log como "decisión clave"
_KEY_PATTERNS = [
    ("Contacto por email:",       "#2ecc71"),
    ("Contacto no encontrado",    "#e74c3c"),
    ("Contacto por teléfono:",    "#2ecc71"),
    ("Contacto creado:",          "#9b59b6"),
    ("Deal encontrado:",          "#2ecc71"),
    ("Sin deal",                  "#e67e22"),
    ("Visita creada:",            "#2ecc71"),
    ("Visita actualizada:",       "#f39c12"),
    ("Visita marcada FAIL:",      "#e74c3c"),
    ("Notas actualizadas",        "#3498db"),
    ("Ignorado:",                 "#555"),
    ("Ignorando",                 "#555"),
    ("ya estaba en FAIL",         "#555"),
    ("no encontrada",             "#e74c3c"),
    ("Fecha sin cambios",         "#555"),
    ("PRUEBA_MAKE",               "#555"),
]

def _key_color(msg: str) -> str | None:
    ml = msg.lower()
    for pattern, color in _KEY_PATTERNS:
        if pattern.lower() in ml:
            return color
    return None


def _render_monitor() -> str:
    all_history = list(state.history)

    # ── Summary rows ──────────────────────────────────────────────────────────
    ACTION_COLOR = {"creada": "#2ecc71", "modificada": "#f39c12", "cancelada": "#e74c3c"}
    ACTION_ICON  = {"creada": "✅",      "modificada": "🔄",       "cancelada": "❌"}

    bloques = ""
    for i, s in enumerate(list(state.summaries)):
        ac      = ACTION_COLOR.get(s["action"], "#aaa")
        icon    = ACTION_ICON.get(s["action"], "·")
        client  = s["client"].replace("<", "&lt;")[:40]
        appt_id = s["appointment_id"]

        # Logs relacionados con esta cita (etiquetados por ContextVar, orden cronológico)
        related  = [e for e in reversed(all_history) if e.get("appt_id") == appt_id]
        msgs_txt = " | ".join(e["message"] for e in related)

        # Breadcrumb de flujo
        path_steps = _build_flow_path(msgs_txt, s["action"])
        flow_bar   = _render_flow_path(path_steps)

        # Filas de log con resaltado de líneas clave
        log_rows = ""
        for entry in related:
            lc       = {"ERROR": "#e74c3c", "WARNING": "#f39c12", "INFO": "#3498db"}.get(entry["level"], "#aaa")
            msg      = entry["message"].replace("<", "&lt;").replace(">", "&gt;")
            kc       = _key_color(entry["message"])
            row_bg   = "#0d0d1f"
            left_bar = ""
            key_style = ""
            if kc:
                row_bg   = "#0a0a18"
                left_bar = f'border-left:3px solid {kc};'
                key_style = f'color:{kc};font-weight:600;'
            log_rows += (
                f'<tr style="background:{row_bg};{left_bar}">'
                f'<td style="color:#888;white-space:nowrap;padding:3px 10px;font-size:.75em">{entry["time"]}</td>'
                f'<td style="color:{lc};padding:3px 6px;font-size:.75em;font-weight:600">{entry["level"]}</td>'
                f'<td style="padding:3px 10px;font-size:.78em;{key_style}color:#ccc;word-break:break-word">{msg}</td>'
                f'</tr>'
            )
        if not log_rows:
            log_rows = '<tr><td colspan="3" style="color:#444;padding:8px 14px;font-size:.78em">Sin logs capturados para esta cita</td></tr>'

        bloques += f"""
        <tr class="sm-head" onclick="toggle({i})" title="Clic para ver log">
          <td class="ts">{s["time"]}</td>
          <td class="sm-arrow" id="arr-{i}">▶</td>
          <td class="sm-from-h">{client}<br><span class="sm-mail">{s["email"]}</span></td>
          <td class="sm-appt">#{appt_id}</td>
          <td style="color:{ac};white-space:nowrap">{icon} {s["action"].capitalize()}</td>
          <td class="ms">{s["result"].replace("<","&lt;")}</td>
        </tr>
        <tr class="sm-detail" id="det-{i}" style="display:none">
          <td colspan="6" style="padding:0;background:#0d0d1f">
            {flow_bar}
            <table style="width:100%;border-collapse:collapse;background:transparent;border:none;border-radius:0;margin:0">
              <tr style="background:#111127">
                <td style="padding:5px 14px;font-size:.75em;color:#555">Bitrix24:</td>
                <td style="padding:5px 4px;font-size:.78em;color:#9b59b6"><strong>{s["bitrix_id"] or "—"}</strong></td>
                <td style="padding:5px 14px;font-size:.75em;color:#555">Acuity:</td>
                <td style="padding:5px 4px;font-size:.78em;color:#3498db"><strong>#{appt_id}</strong></td>
                <td style="padding:5px 14px;font-size:.75em;color:#555">Email:</td>
                <td style="padding:5px 4px;font-size:.78em;color:#aaa">{s["email"]}</td>
                <td style="padding:5px 14px;font-size:.75em;color:#333;text-align:right">{len(related)} logs</td>
              </tr>
              {log_rows}
            </table>
          </td>
        </tr>"""

    if not bloques:
        bloques = '<tr><td colspan="6" style="text-align:center;color:#555;padding:30px">Sin citas procesadas aún…</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Monitor — Scheduling Visitas</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    :root{{
      --bg:#F1F5F9;--su:#fff;--bo:#E2E8F0;--boh:#CBD5E1;
      --t1:#0F172A;--t2:#475569;--t3:#94A3B8;
      --grn:#059669;--grn-bg:#ECFDF5;--grn-brd:rgba(5,150,105,.18);
      --red:#DC2626;--red-bg:#FEF2F2;--red-brd:rgba(220,38,38,.18);
      --amb:#D97706;--amb-bg:#FFFBEB;--amb-brd:rgba(217,119,6,.18);
      --rs:6px;
    }}
    @media(prefers-color-scheme:dark){{:root{{
      --bg:#0F172A;--su:#1E293B;--bo:#334155;--boh:#475569;
      --t1:#F1F5F9;--t2:#94A3B8;--t3:#475569;
      --grn-bg:#022c22;--red-bg:#1e0606;--amb-bg:#1c1107;
      --grn-brd:rgba(5,150,105,.3);--red-brd:rgba(220,38,38,.3);--amb-brd:rgba(217,119,6,.3);
    }}}}
    :root[data-theme=dark]{{--bg:#0F172A;--su:#1E293B;--bo:#334155;--boh:#475569;--t1:#F1F5F9;--t2:#94A3B8;--t3:#475569;--grn-bg:#022c22;--red-bg:#1e0606;--amb-bg:#1c1107;--grn-brd:rgba(5,150,105,.3);--red-brd:rgba(220,38,38,.3);--amb-brd:rgba(217,119,6,.3)}}
    :root[data-theme=light]{{--bg:#F1F5F9;--su:#fff;--bo:#E2E8F0;--boh:#CBD5E1;--t1:#0F172A;--t2:#475569;--t3:#94A3B8;--grn-bg:#ECFDF5;--red-bg:#FEF2F2;--amb-bg:#FFFBEB;--grn-brd:rgba(5,150,105,.18);--red-brd:rgba(220,38,38,.18);--amb-brd:rgba(217,119,6,.18)}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;font-size:14px;line-height:1.5;color:var(--t1);background:var(--bg);font-variant-numeric:tabular-nums}}
    /* Nav */
    .nav{{position:sticky;top:0;z-index:50;background:var(--su);border-bottom:1px solid var(--bo);display:flex;align-items:center;gap:10px;padding:0 18px;height:48px}}
    .nav-title{{font-size:14px;font-weight:700;color:var(--t1);display:flex;align-items:center;gap:8px;white-space:nowrap}}
    .live{{display:inline-flex;align-items:center;gap:4px;background:var(--grn-bg);color:var(--grn);border:1px solid var(--grn-brd);border-radius:20px;padding:2px 9px;font-size:11px;font-weight:700;letter-spacing:.04em}}
    .live::before{{content:'';width:6px;height:6px;border-radius:50%;background:currentColor;flex-shrink:0}}
    .nav-actions{{margin-left:auto;display:flex;gap:6px;align-items:center;flex-shrink:0}}
    .nb{{padding:5px 11px;border-radius:var(--rs);font-size:12px;font-weight:500;color:var(--t2);border:1px solid var(--bo);background:var(--su);cursor:pointer;font-family:inherit;transition:background .15s}}
    .nb:hover{{background:var(--bg)}}
    .nb:disabled{{opacity:.35;cursor:default}}
    .nb-danger{{color:var(--red);border-color:var(--red-brd)}}
    .nb-danger:hover{{background:var(--red-bg)}}
    /* Content */
    .content{{padding:16px 18px}}
    .sub{{font-size:12px;color:var(--t3);margin:0 0 12px}}
    /* Table */
    table{{width:100%;border-collapse:collapse;background:var(--su);border:1px solid var(--bo);border-radius:8px;overflow:hidden;margin-bottom:24px}}
    th{{background:var(--bg);color:var(--t2);padding:8px 12px;text-align:left;font-size:.78em;letter-spacing:.5px;font-weight:600;text-transform:uppercase}}
    td{{padding:6px 12px;font-size:.88em;border-top:1px solid var(--bo);color:var(--t2);vertical-align:top}}
    /* Expandable rows - level 1 (calls/emails) */
    .sm-head{{cursor:pointer;transition:background .1s}}
    .sm-head:hover td{{background:var(--bg)}}
    .sm-arrow,.fn-arrow{{width:20px;padding:6px 4px;color:var(--t3);font-size:.85em}}
    .sm-detail{{background:var(--su)}}
    .sm-tel{{padding:6px 12px;color:var(--t1);min-width:140px}}
    .sm-label{{color:var(--t3);font-size:.85em;white-space:nowrap}}
    .sm-val{{font-size:.88em;color:var(--t2)}}
    .ts{{white-space:nowrap;width:130px;padding:6px 12px;color:var(--t1);font-weight:600}}
    /* Expandable rows - level 2 (functions) */
    .fn-head{{cursor:pointer;background:var(--bg);transition:background .1s;border-top:1px solid var(--bo)}}
    .fn-head:hover td{{background:var(--boh)}}
    .fn-ts{{white-space:nowrap;width:115px;padding:5px 12px;color:var(--t3);font-size:.85em}}
    .fn-detail td{{background:var(--bg);font-size:.85em}}
    .wh-cell{{padding:5px 10px}}
    /* Badges / chips */
    .badge{{background:var(--grn-bg);color:var(--grn);border:1px solid var(--grn-brd);padding:1px 8px;border-radius:10px;font-size:.72em;font-weight:700}}
    /* Scrollbar */
    ::-webkit-scrollbar{{width:6px;height:6px}}
    ::-webkit-scrollbar-track{{background:var(--bg)}}
    ::-webkit-scrollbar-thumb{{background:var(--bo);border-radius:3px}}
    /* Scheduling Visitas specific */
    .sm-from-h{{padding:5px 10px;min-width:140px}}
    .sm-appt{{padding:5px 10px;font-size:.78em;color:#3498db;white-space:nowrap}}
    .sm-mail{{color:var(--t3);font-size:.75em}}
  </style>
</head>
<body>
<div class="nav">
  <span class="nav-title">🗓️ Scheduling Visitas <span class="live">live</span></span>
  <div class="nav-actions">
    <button class="nb" id="tab-sum" onclick="collapseAll()">⊟ Summary</button>
    <button class="nb nb-danger" id="btn-pausar" onclick="pauseRefresh()">⏸ Pausar</button>
    <button class="nb" id="btn-retomar" onclick="resumeRefresh()" disabled>▶ Retomar</button>
  </div>
</div>
<div class="content">
  <p class="sub">Acuity → <code>appointment.scheduled</code> <code>appointment.rescheduled</code> <code>appointment.canceled</code> &nbsp;·&nbsp; refresco 5 s</p>

  <table>
    <thead><tr><th>Fecha y hora</th><th></th><th>Cliente</th><th>Acuity ID</th><th>Acción</th><th>Resultado</th></tr></thead>
    <tbody>{bloques}</tbody>
  </table>
</div>
  <script>
    function collapseAll() {{
      document.querySelectorAll('.sm-detail').forEach(d => d.style.display = 'none');
      document.querySelectorAll('.sm-arrow').forEach(a => a.textContent = '▶');
    }}
    function toggle(i) {{
      const det = document.getElementById('det-' + i);
      const arr = document.getElementById('arr-' + i);
      if (det.style.display === 'none') {{
        det.style.display = 'table-row';
        arr.textContent = '▼';
      }} else {{
        det.style.display = 'none';
        arr.textContent = '▶';
      }}
    }}
    const INTERVAL = 5;
    let reloader;
    function startTimers() {{
      reloader = setInterval(softReload, INTERVAL * 1000);
    }}
    function pauseRefresh() {{
      clearInterval(reloader);
      document.getElementById('btn-pausar').disabled = true;
      document.getElementById('btn-retomar').disabled = false;
    }}
    function resumeRefresh() {{
      document.getElementById('btn-pausar').disabled = false;
      document.getElementById('btn-retomar').disabled = true;
      startTimers();
    }}
    async function softReload() {{
      try {{
        const openIds = {{}};
        document.querySelectorAll('[id]').forEach(function(el) {{
          if (el.style.display && el.style.display !== 'none') openIds[el.id] = el.style.display;
        }});
        const res = await fetch(window.location.href, {{cache:'no-store'}});
        if (!res.ok) return;
        const html = await res.text();
        const doc = new DOMParser().parseFromString(html, 'text/html');
        const newBodyHTML = Array.from(doc.body.children).filter(function(el) {{ return el.tagName !== 'SCRIPT'; }}).map(function(el) {{ return el.outerHTML; }}).join('');
        document.body.innerHTML = newBodyHTML;
        Object.keys(openIds).forEach(function(id) {{ var el = document.getElementById(id); if (el) el.style.display = openIds[id]; }});
      }} catch(e) {{ console.error('Soft reload error:', e); }}
    }}
    startTimers();
  </script>
</body>
</html>"""
