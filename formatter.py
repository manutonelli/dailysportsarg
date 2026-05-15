"""
Formatea los partidos (fútbol + F1) para enviarlos como mensajes de Telegram (HTML).
Por defecto muestra solo ligas principales. Con /partidos todo muestra todo.
"""

from datetime import datetime, timedelta
from typing import Optional
import pytz

from scraper import Liga, Partido
from f1 import EventoF1, SesionF1

MAX_MSG_LEN = 4000

# ── Filtro de ligas principales ───────────────────────────────────────────────
# Solo estas combinaciones (pais, substring_nombre) pasan el filtro por defecto.
# Argentina pasa siempre sin importar el nombre de la liga.

LIGAS_PERMITIDAS = [
    # Europa top 5 — nombres en inglés Y español (Promiedos usa español)
    ("england",      "premier league"),
    ("inglaterra",   "premier league"),
    ("spain",        "laliga"),
    ("spain",        "la liga"),
    ("españa",       "laliga"),
    ("españa",       "la liga"),
    ("germany",      "bundesliga"),
    ("alemania",     "bundesliga"),
    ("italy",        "serie a"),
    ("italia",       "serie a"),
    ("france",       "ligue 1"),
    ("francia",      "ligue 1"),
    ("portugal",     "primeira liga"),
    ("portugal",     "liga portugal"),
    ("netherlands",  "eredivisie"),
    ("holanda",      "eredivisie"),
    # Copas UEFA
    ("europa",       "champions league"),
    ("europa",       "europa league"),
    ("europa",       "conference league"),
    ("europe",       "champions league"),
    ("europe",       "europa league"),
    ("internacional","champions league"),
    ("internacional","europa league"),
    ("internacional","conference league"),
    # Copas nacionales top 5
    ("england",      "fa cup"),
    ("inglaterra",   "fa cup"),
    ("spain",        "copa del rey"),
    ("españa",       "copa del rey"),
    ("germany",      "dfb pokal"),
    ("alemania",     "dfb pokal"),
    ("italy",        "coppa italia"),
    ("italia",       "coppa italia"),
    ("france",       "coupe de france"),
    ("francia",      "copa de francia"),
    # Sudamérica continental
    ("sudamérica",   "libertadores"),
    ("sudamerica",   "libertadores"),
    ("south america","libertadores"),
    ("internacional","libertadores"),
    ("sudamérica",   "sudamericana"),
    ("sudamerica",   "sudamericana"),
    ("south america","sudamericana"),
    ("internacional","sudamericana"),
    # Ligas nacionales sudamérica
    ("brazil",       "série a"),
    ("brasil",       "série a"),
    ("brasil",       "brasileirao"),
    ("mexico",       "liga mx"),
    ("méxico",       "liga mx"),
    ("uruguay",      "primera división"),
    ("uruguay",      "primera division"),
    ("chile",        "primera división"),
    ("chile",        "primera division"),
    ("colombia",     "liga betplay"),
    ("colombia",     "primera a"),
    ("peru",         "liga 1"),
    ("perú",         "liga 1"),
    # Torneos de selecciones (pais vacío = cualquier país)
    ("",             "world cup"),
    ("",             "copa america"),
    ("",             "copa américa"),
    ("",             "nations league"),
    ("",             "eliminatorias"),
    ("",             "mundial"),
]

# Palabras que EXCLUYEN una liga aunque coincida con las anteriores
PALABRAS_EXCLUIDAS = {
    "u17", "u20", "u21", "u23",
    "women", "femenino", "femenina", "damas",
    "amateur", "youth", "juvenile", "reserva", "reserve",
    "primavera", "regional", "provincial",
    # Subdivisiones que generan duplicados (solo para no-Argentina)
    "group a", "group b", "group c", "group d",
    "playoffs", "playoff",
    "promotion", "relegation", "championship round",
    "relegation round", "promotion round",
}


def _es_liga_principal(liga: Liga) -> bool:
    nombre = liga.nombre.lower().strip()
    pais   = liga.pais.lower().strip()

    # 1. Excluir palabras prohibidas
    for excluida in PALABRAS_EXCLUIDAS:
        if excluida in nombre:
            # Argentina: solo excluir juveniles/femeninas, no fases
            if "argentina" in pais and excluida not in {
                "u17", "u20", "u21", "u23",
                "women", "femenino", "femenina", "damas",
                "amateur", "youth", "juvenile", "reserva", "reserve",
            }:
                pass  # Argentina sigue pasando aunque tenga playoff/apertura
            else:
                return False

    # 2. Argentina siempre incluida (salvo juveniles/femeninas)
    if "argentina" in pais:
        return True

    # 3. Liga MX exacta (sin playoffs/clausura que ya fueron filtrados)
    # Re-chequear nombre limpio para Mexico
    if ("mexico" in pais or "méxico" in pais) and "liga mx" in nombre:
        return True

    # 4. Verificar combinación país + nombre
    for pais_key, liga_key in LIGAS_PERMITIDAS:
        if pais_key == "":
            if liga_key in nombre:
                return True
        elif pais_key in pais and liga_key in nombre:
            return True

    return False


# ── Banderas ──────────────────────────────────────────────────────────────────

BANDERAS = {
    "ARGENTINA": "🇦🇷",
    "SPAIN": "🇪🇸",     "ESPAÑA": "🇪🇸",
    "ENGLAND": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "INGLATERRA": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
    "GERMANY": "🇩🇪",   "ALEMANIA": "🇩🇪",
    "ITALY": "🇮🇹",     "ITALIA": "🇮🇹",
    "FRANCE": "🇫🇷",    "FRANCIA": "🇫🇷",
    "PORTUGAL": "🇵🇹",
    "BRAZIL": "🇧🇷",    "BRASIL": "🇧🇷",
    "URUGUAY": "🇺🇾",
    "COLOMBIA": "🇨🇴",
    "CHILE": "🇨🇱",
    "MEXICO": "🇲🇽",    "MÉXICO": "🇲🇽",
    "USA": "🇺🇸",       "ESTADOS UNIDOS": "🇺🇸",
    "NETHERLANDS": "🇳🇱","HOLANDA": "🇳🇱",
    "EUROPA": "🇪🇺",    "EUROPE": "🇪🇺",
    "SUDAMÉRICA": "🌎",  "SUDAMERICA": "🌎", "SOUTH AMERICA": "🌎",
}


def _bandera(pais: str) -> str:
    p = pais.upper()
    for key, flag in BANDERAS.items():
        if key in p:
            return flag
    return "⚽"


def _linea_partido(p: Partido) -> str:
    if p.resultado:
        en_vivo = "🔴 " if "vivo" in p.estado.lower() else ""
        return f"  {en_vivo}<code>{p.hora}</code> {p.local} <b>{p.resultado}</b> {p.visitante}"
    return f"  <code>{p.hora}</code> {p.local} vs {p.visitante}"


# ── Formateador principal ─────────────────────────────────────────────────────

def formatear_mensaje(
    ligas: list,
    evento_f1: Optional[EventoF1] = None,
    fecha=None,
    mostrar_todo: bool = False,
) -> list[str]:
    tz   = pytz.timezone("America/Argentina/Buenos_Aires")
    ahora = datetime.now(tz)
    hoy   = ahora.date()

    if fecha is None:
        fecha = hoy

    ligas_mostrar = ligas if mostrar_todo else [l for l in ligas if _es_liga_principal(l)]

    total_filtrado = sum(len(l.partidos) for l in ligas_mostrar)
    total_real     = sum(len(l.partidos) for l in ligas)
    ocultos        = total_real - total_filtrado

    # Encabezado de fecha
    if fecha == hoy:
        fecha_str = f"Hoy · {ahora.strftime('%A %d de %B de %Y').capitalize()}"
    elif fecha == hoy + timedelta(days=1):
        fecha_str = f"Mañana · {datetime.combine(fecha, datetime.min.time()).strftime('%A %d de %B de %Y').capitalize()}"
    else:
        fecha_str = datetime.combine(fecha, datetime.min.time()).strftime("%A %d de %B de %Y").capitalize()

    tiene_f1 = evento_f1 is not None and bool(evento_f1.sesiones_hoy)
    pie = f"\n➕ <i>+{ocultos} partidos de otras ligas. Usá /partidos todo para ver todo.</i>" if ocultos > 0 and not mostrar_todo else ""

    encabezado = (
        f"{'🏎️⚽' if tiene_f1 else '⚽'} <b>AGENDA DEPORTIVA</b>\n"
        f"📅 {fecha_str}\n"
        f"📊 {total_filtrado} partido{'s' if total_filtrado != 1 else ''}"
        f"{f' de {total_real} totales' if ocultos > 0 and not mostrar_todo else ''}"
        f"{' · F1 🏎️' if tiene_f1 else ''}\n"
        f"{'─' * 30}\n\n"
    )

    mensajes: list[str] = []
    buffer = encabezado

    if tiene_f1:
        buffer += _bloque_f1(evento_f1)

    for liga in ligas_mostrar:
        bandera     = _bandera(liga.pais)
        header_liga = (
            f"{bandera} <b>{liga.pais} · {liga.nombre.upper()}</b>\n"
            if liga.pais else
            f"{bandera} <b>{liga.nombre.upper()}</b>\n"
        )
        lineas = "\n".join(_linea_partido(p) for p in liga.partidos)
        bloque = f"{header_liga}{lineas}\n\n"

        if len(buffer) + len(bloque) > MAX_MSG_LEN:
            mensajes.append(buffer.rstrip())
            buffer = f"⚽ <b>AGENDA</b> (continuación)\n{'─' * 30}\n\n"

        buffer += bloque

    if pie:
        buffer += pie

    if buffer.strip():
        mensajes.append(buffer.rstrip())

    return mensajes or ["⚠️ No se encontraron eventos deportivos para esta fecha."]


# ── F1 ────────────────────────────────────────────────────────────────────────

def formatear_f1_completo(evento: EventoF1) -> str:
    titulo = (
        f"🏎️ <b>FÓRMULA 1 — {evento.temporada}</b>\n"
        f"{'─' * 30}\n"
        f"{_bandera(evento.pais)} <b>{evento.gran_premio}</b>\n"
        f"Ronda {evento.ronda} · {evento.ciudad}, {evento.pais}\n"
        f"🏟️ {evento.circuito}\n\n"
    )
    titulo += "<b>📋 Sesiones de hoy (hora Argentina):</b>\n" if evento.sesiones_hoy else "<b>📋 Programa del fin de semana:</b>\n"
    for s in evento.sesiones_hoy:
        titulo += f"  {_icono_sesion(s.tipo)} <code>{s.hora_local}</code>  {s.nombre}\n"
    return titulo.rstrip()


def _bloque_f1(evento: EventoF1) -> str:
    lineas = [f"  {_icono_sesion(s.tipo)} <code>{s.hora_local}</code>  {s.nombre}" for s in evento.sesiones_hoy]
    return (
        f"🏎️ <b>FÓRMULA 1 — {evento.gran_premio}</b>\n"
        f"{_bandera(evento.pais)} {evento.ciudad}, {evento.pais}\n"
        f"{chr(10).join(lineas)}\n\n"
        f"{'─' * 30}\n\n"
    )


def _icono_sesion(tipo: str) -> str:
    return {"practice": "🔧", "qualifying": "⏱️", "sprint": "⚡", "race": "🏁"}.get(tipo, "📍")
