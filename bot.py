#!/usr/bin/env python3
"""
Bot de Telegram - Fútbol + Fórmula 1
"""

import asyncio
import logging
import os
from datetime import datetime
import pytz

from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes

from scraper import obtener_partidos
from f1 import obtener_evento_f1_hoy, obtener_proxima_carrera
from formatter import formatear_mensaje, formatear_f1_completo
from keep_alive import keep_alive

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Configuración ──────────────────────────────────────────────────────────────
TOKEN        = os.environ.get("TELEGRAM_BOT_TOKEN", "TU_TOKEN_AQUI")
CHAT_IDS_RAW = os.environ.get("TELEGRAM_CHAT_IDS", "")
HORA_ENVIO   = int(os.environ.get("HORA_ENVIO", "8"))
ZONA_HORARIA = os.environ.get("ZONA_HORARIA", "America/Argentina/Buenos_Aires")

# ── Suscriptores ───────────────────────────────────────────────────────────────

def get_chat_ids() -> list[str]:
    ids = set()
    if CHAT_IDS_RAW:
        for cid in CHAT_IDS_RAW.split(","):
            cid = cid.strip()
            if cid:
                ids.add(cid)
    if os.path.exists("subscribers.txt"):
        with open("subscribers.txt") as f:
            for line in f:
                cid = line.strip()
                if cid:
                    ids.add(cid)
    return list(ids)


def save_chat_id(chat_id: str):
    if chat_id not in get_chat_ids():
        with open("subscribers.txt", "a") as f:
            f.write(f"{chat_id}\n")
        logger.info(f"Nuevo suscriptor: {chat_id}")


def remove_chat_id(chat_id: str):
    updated = [c for c in get_chat_ids() if c != chat_id]
    with open("subscribers.txt", "w") as f:
        for cid in updated:
            f.write(f"{cid}\n")
    logger.info(f"Suscriptor eliminado: {chat_id}")


# ── Envío principal ────────────────────────────────────────────────────────────

async def enviar_agenda(bot: Bot, chat_id: str | None = None):
    """Obtiene fútbol + F1 y envía el mensaje diario."""
    logger.info("Obteniendo agenda deportiva...")

    # Fútbol y F1 en paralelo
    partidos, evento_f1 = await asyncio.gather(
        obtener_partidos(),
        obtener_evento_f1_hoy(),
    )

    if not partidos and not evento_f1:
        texto = "⚠️ No se encontraron eventos deportivos para hoy."
        recipients = [chat_id] if chat_id else get_chat_ids()
        for cid in recipients:
            try:
                await bot.send_message(chat_id=cid, text=texto)
            except Exception as e:
                logger.error(f"Error enviando a {cid}: {e}")
        return

    mensajes = formatear_mensaje(partidos, evento_f1)
    recipients = [chat_id] if chat_id else get_chat_ids()

    for cid in recipients:
        try:
            for msg in mensajes:
                await bot.send_message(
                    chat_id=cid,
                    text=msg,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"Error enviando a {cid}: {e}")


async def job_diario(context: ContextTypes.DEFAULT_TYPE):
    await enviar_agenda(context.bot)


# ── Comandos ───────────────────────────────────────────────────────────────────

async def cmd_start(update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    save_chat_id(chat_id)
    tz = pytz.timezone(ZONA_HORARIA)
    hora_str = datetime.now(tz).replace(hour=HORA_ENVIO, minute=0).strftime("%H:%M")

    await update.message.reply_text(
        f"⚽🏎️ <b>¡Bienvenido al Bot de Deportes!</b>\n\n"
        f"Recibirás automáticamente todos los días a las <b>{hora_str} hs</b>:\n"
        f"• Todos los partidos de fútbol del día\n"
        f"• Sesiones de Fórmula 1 cuando las haya\n\n"
        f"📋 <b>Comandos:</b>\n"
        f"/agenda — Ver la agenda de hoy\n"
        f"/partidos — Solo fútbol de hoy\n"
        f"/f1 — Info de la próxima carrera F1\n"
        f"/stop — Cancelar suscripción\n"
        f"/ayuda — Ayuda",
        parse_mode="HTML"
    )


async def cmd_stop(update, context: ContextTypes.DEFAULT_TYPE):
    remove_chat_id(str(update.effective_chat.id))
    await update.message.reply_text(
        "🔕 Te diste de baja. Ya no recibirás notificaciones.\n"
        "Podés volver cuando quieras con /start"
    )


async def cmd_agenda(update, context: ContextTypes.DEFAULT_TYPE):
    """Fútbol + F1 juntos."""
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text("⏳ Buscando agenda deportiva de hoy...")
    await enviar_agenda(context.bot, chat_id=chat_id)


async def cmd_partidos(update, context: ContextTypes.DEFAULT_TYPE):
    """
    /partidos           → ligas principales de hoy
    /partidos todo      → todas las ligas de hoy
    /partidos mañana    → ligas principales de mañana
    /partidos 20/05     → ligas principales de esa fecha
    /partidos todo 20/05 → todas las ligas de esa fecha
    """
    chat_id = str(update.effective_chat.id)
    from scraper import parsear_fecha

    args = list(context.args) if context.args else []
    mostrar_todo = False
    fecha = None

    # Detectar "todo" en los argumentos
    if "todo" in args:
        mostrar_todo = True
        args.remove("todo")

    # Detectar fecha en el resto
    if args:
        texto = " ".join(args)
        fecha = parsear_fecha(texto)
        if fecha is None:
            await update.message.reply_text(
                "⚠️ No entendí la fecha. Ejemplos:\n"
                "/partidos mañana\n"
                "/partidos 20/05\n"
                "/partidos todo\n"
                "/partidos todo 20/05"
            )
            return

    tz = pytz.timezone(ZONA_HORARIA)
    hoy = datetime.now(tz).date()
    if fecha is None or fecha == hoy:
        fecha_texto = "de hoy"
    elif fecha == hoy + __import__('datetime').timedelta(days=1):
        fecha_texto = "de mañana"
    else:
        fecha_texto = f"del {fecha.strftime('%d/%m/%Y')}"

    await update.message.reply_text(
        f"⏳ Buscando partidos {fecha_texto}"
        f"{' (todas las ligas)' if mostrar_todo else ''}..."
    )

    partidos = await obtener_partidos(fecha)
    mensajes = formatear_mensaje(partidos, evento_f1=None, fecha=fecha, mostrar_todo=mostrar_todo)
    for msg in mensajes:
        await context.bot.send_message(
            chat_id=chat_id, text=msg,
            parse_mode="HTML", disable_web_page_preview=True
        )
        await asyncio.sleep(0.3)


async def cmd_f1(update, context: ContextTypes.DEFAULT_TYPE):
    """Info de F1: si hay sesión hoy la muestra, si no muestra la próxima carrera."""
    await update.message.reply_text("🏎️ Buscando info de F1...")

    # Primero intentar sesión de hoy
    evento = await obtener_evento_f1_hoy()

    if evento:
        msg = formatear_f1_completo(evento)
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    # Si no hay nada hoy, mostrar la próxima
    proximo = await obtener_proxima_carrera()
    if proximo:
        tz = pytz.timezone(ZONA_HORARIA)
        msg = (
            f"🏎️ <b>FÓRMULA 1 — Próxima carrera</b>\n"
            f"{'─' * 30}\n"
            f"🏆 <b>{proximo.gran_premio}</b>\n"
            f"📍 {proximo.ciudad}, {proximo.pais}\n"
            f"🏟️ {proximo.circuito}\n"
            f"🔢 Ronda {proximo.ronda} de {proximo.temporada}\n\n"
            f"<b>📋 Programa (hora Argentina):</b>\n"
        )
        for s in proximo.sesiones_hoy:
            iconos = {"practice": "🔧", "qualifying": "⏱️", "sprint": "⚡", "race": "🏁"}
            msg += f"  {iconos.get(s.tipo,'📍')} {s.hora_local}  {s.nombre}\n"
        await update.message.reply_text(msg, parse_mode="HTML")
    else:
        await update.message.reply_text(
            "🏎️ No se pudo obtener información de F1 en este momento.\n"
            "Podés consultar en https://www.formula1.com/en/racing/2025"
        )


async def cmd_ayuda(update, context: ContextTypes.DEFAULT_TYPE):
    tz = pytz.timezone(ZONA_HORARIA)
    hora_str = datetime.now(tz).replace(hour=HORA_ENVIO, minute=0).strftime("%H:%M")
    await update.message.reply_text(
        f"⚽🏎️ <b>Bot de Deportes — Ayuda</b>\n"
        f"{'─' * 30}\n\n"

        f"📌 <b>/start</b>\n"
        f"Te suscribís al bot. A partir de ahí recibís automáticamente "
        f"la agenda deportiva todos los días a las <b>{hora_str} hs</b>.\n\n"

        f"📅 <b>/agenda</b>\n"
        f"Muestra todos los partidos de fútbol del día junto con las "
        f"sesiones de Fórmula 1 si las hay (práctica, clasificación, carrera).\n\n"

        f"⚽ <b>/partidos</b>\n"
        f"Muestra solo los partidos de fútbol de hoy, ordenados por hora. "
        f"Filtra automáticamente las ligas más importantes.\n\n"

        f"⚽ <b>/partidos [fecha]</b>\n"
        f"Muestra los partidos de una fecha específica. Ejemplos:\n"
        f"  • /partidos mañana\n"
        f"  • /partidos ayer\n"
        f"  • /partidos 20/05\n"
        f"  • /partidos 20/05/2026\n\n"

        f"⚽ <b>/partidos todo</b>\n"
        f"Muestra absolutamente todos los partidos del día, incluyendo ligas menores. "
        f"También funciona con fecha: /partidos todo 20/05\n\n"

        f"🏎️ <b>/f1</b>\n"
        f"Muestra información de Fórmula 1. Si hoy hay una sesión "
        f"(práctica, clasificación o carrera) la muestra con el horario. "
        f"Si no hay nada hoy, muestra el programa completo de la próxima carrera.\n\n"

        f"🔕 <b>/stop</b>\n"
        f"Cancelás tu suscripción. Dejás de recibir la agenda diaria automática. "
        f"Podés volver a suscribirte cuando quieras con /start.\n\n"

        f"❓ <b>/ayuda</b>\n"
        f"Muestra este mensaje.\n\n"

        f"{'─' * 30}\n"
        f"📡 <b>Fuentes de datos:</b>\n"
        f"⚽ TheSportsDB · football-data.org\n"
        f"🏎️ Jolpica F1 API",
        parse_mode="HTML",
    )


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("stop",     cmd_stop))
    app.add_handler(CommandHandler("agenda",   cmd_agenda))
    app.add_handler(CommandHandler("partidos", cmd_partidos))
    app.add_handler(CommandHandler("f1",       cmd_f1))
    app.add_handler(CommandHandler("ayuda",    cmd_ayuda))

    tz = pytz.timezone(ZONA_HORARIA)
    app.job_queue.run_daily(
        job_diario,
        time=datetime.now(tz).replace(hour=HORA_ENVIO, minute=0, second=0).timetz(),
        name="agenda_diaria",
    )

    logger.info(f"Bot iniciado. Envío diario a las {HORA_ENVIO}:00 ({ZONA_HORARIA})")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    import asyncio, sys
    if sys.version_info >= (3, 12):
        asyncio.set_event_loop(asyncio.new_event_loop())
    keep_alive()  # Inicia servidor HTTP para Render
    main()
