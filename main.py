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

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse

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


@app.get("/monitor", response_class=HTMLResponse)
async def monitor():
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
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:monospace; background:#0f0f1a; padding:24px; color:#eee; }}
  .topbar {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:6px; flex-wrap:wrap; gap:10px; }}
  h1 {{ color:#e94560; font-size:1.3em; }}
  .badge {{ background:#2ecc71; color:#fff; padding:2px 10px; border-radius:10px; font-size:.72em; margin-left:8px; vertical-align:middle; }}
  .toolbar {{ display:flex; gap:8px; align-items:center; }}
  .btn {{ background:#16213e; border:1px solid #2a2a4a; color:#ccc; padding:5px 14px; border-radius:6px; cursor:pointer; font-family:monospace; font-size:12px; transition:background .15s; text-decoration:none; display:inline-block; }}
  .btn:hover {{ background:#1f2f50; color:#fff; }}
  .btn:disabled {{ opacity:.35; cursor:default; }}
  .btn-pause  {{ border-color:#e74c3c; color:#e74c3c; }}
  .btn-resume {{ border-color:#2ecc71; color:#2ecc71; }}
  .btn-tab    {{ border-color:#9b59b6; color:#9b59b6; }}
  #ticker {{ color:#555; font-size:12px; min-width:50px; text-align:right; }}
  .sub {{ color:#555; font-size:12px; margin:0 0 16px; }}
  .sub code {{ background:#16213e; padding:1px 6px; border-radius:3px; margin:0 2px; color:#9b59b6; }}
  table {{ width:100%; border-collapse:collapse; background:#1a1a2e; border:1px solid #2a2a4a; border-radius:8px; overflow:hidden; margin-bottom:24px; }}
  th {{ background:#16213e; color:#aaa; padding:8px 12px; text-align:left; font-size:.8em; letter-spacing:.5px; }}
  .ts {{ white-space:nowrap; width:115px; padding:5px 10px; color:#bbb; font-size:.78em; }}
  .lv {{ width:70px; padding:5px 8px; font-size:.78em; font-weight:600; }}
  .ms {{ padding:5px 10px; font-size:.82em; word-break:break-word; color:#ddd; }}
  td {{ padding:5px 10px; font-size:.82em; vertical-align:top; }}
  .sm-head {{ cursor:pointer; transition:background .1s; }}
  .sm-head:hover td {{ background:#1f2540; }}
  .sm-arrow {{ width:20px; padding:5px 4px; color:#555; font-size:.7em; }}
  .sm-from-h {{ padding:5px 10px; font-size:.82em; min-width:140px; }}
  .sm-appt {{ padding:5px 10px; font-size:.78em; color:#3498db; white-space:nowrap; }}
  .sm-mail {{ color:#555; font-size:.75em; }}
</style>
</head>
<body>
  <div class="topbar">
    <h1>🗓️ Scheduling Visitas <span class="badge">live</span></h1>
    <div class="toolbar">
      <button class="btn btn-tab" id="tab-sum" onclick="collapseAll()">&#9783; Summary</button>
      <button class="btn btn-pause"  id="btn-pausar"  onclick="pauseRefresh()">⏸ Pausar</button>
      <button class="btn btn-resume" id="btn-retomar" onclick="resumeRefresh()" disabled>▶ Retomar</button>
      <span id="ticker">5 s</span>
    </div>
  </div>
  <p class="sub">Acuity → <code>appointment.scheduled</code> <code>appointment.rescheduled</code> <code>appointment.canceled</code> &nbsp;·&nbsp; refresco 5 s</p>

  <table>
    <thead><tr><th>Fecha y hora</th><th></th><th>Cliente</th><th>Acuity ID</th><th>Acción</th><th>Resultado</th></tr></thead>
    <tbody>{bloques}</tbody>
  </table>

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
    let remaining = INTERVAL, countdown, reloader;
    function startTimers() {{
      remaining = INTERVAL;
      countdown = setInterval(() => {{
        remaining--;
        document.getElementById('ticker').textContent = remaining + ' s';
        if (remaining <= 0) remaining = INTERVAL;
      }}, 1000);
      reloader = setInterval(() => location.reload(), INTERVAL * 1000);
    }}
    function pauseRefresh() {{
      clearInterval(countdown); clearInterval(reloader);
      document.getElementById('ticker').textContent = '—';
      document.getElementById('btn-pausar').disabled = true;
      document.getElementById('btn-retomar').disabled = false;
    }}
    function resumeRefresh() {{
      document.getElementById('btn-pausar').disabled = false;
      document.getElementById('btn-retomar').disabled = true;
      startTimers();
    }}
    startTimers();
  </script>
</body>
</html>"""
