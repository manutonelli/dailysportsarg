"""
Scraper de partidos de fútbol.
Fuentes:
  1. Sofascore (API no oficial, sin clave, cobertura total mundial)
  2. ESPN API pública (ligas top)
  3. football-data.org (ligas europeas, con token gratuito)
"""

import asyncio
import logging
import os
import re
from datetime import date, datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional

import httpx
import pytz

logger = logging.getLogger(__name__)

TZ_ARG = pytz.timezone("America/Argentina/Buenos_Aires")
FOOTBALL_DATA_TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN", "")

HEADERS_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
}

ESPN_SLUGS = [
    ("arg.1",                 "Primera División",     "Argentina"),
    ("arg.2",                 "Primera Nacional",     "Argentina"),
    ("conmebol.libertadores", "Copa Libertadores",    "Sudamérica"),
    ("conmebol.sudamericana", "Copa Sudamericana",    "Sudamérica"),
    ("uefa.champions",        "Champions League",     "Europa"),
    ("uefa.europa",           "Europa League",        "Europa"),
    ("esp.1",                 "La Liga",              "España"),
    ("eng.1",                 "Premier League",       "Inglaterra"),
    ("ger.1",                 "Bundesliga",           "Alemania"),
    ("ita.1",                 "Serie A",              "Italia"),
    ("fra.1",                 "Ligue 1",              "Francia"),
    ("por.1",                 "Primeira Liga",        "Portugal"),
    ("ned.1",                 "Eredivisie",           "Holanda"),
    ("mex.1",                 "Liga MX",              "México"),
    ("bra.1",                 "Brasileirao",          "Brasil"),
    ("usa.1",                 "MLS",                  "Estados Unidos"),
]


@dataclass
class Partido:
    liga: str
    pais: str
    hora: str
    local: str
    visitante: str
    resultado: str = ""
    estado: str = "Por jugar"


@dataclass
class Liga:
    nombre: str
    pais: str
    partidos: list = field(default_factory=list)


async def obtener_partidos(fecha: Optional[date] = None) -> list:
    if fecha is None:
        fecha = datetime.now(TZ_ARG).date()

    resultados = await asyncio.gather(
        _desde_espn(fecha),
        _desde_sofascore(fecha),
        _desde_football_data(fecha) if FOOTBALL_DATA_TOKEN else _vacio(),
        return_exceptions=True,
    )

    ligas_espn  = resultados[0] if isinstance(resultados[0], list) else []
    ligas_sofa  = resultados[1] if isinstance(resultados[1], list) else []
    ligas_fdata = resultados[2] if isinstance(resultados[2], list) else []

    return _mergear(ligas_espn, ligas_sofa, ligas_fdata)


async def _vacio():
    return []


# ── ESPN ──────────────────────────────────────────────────────────────────────

async def _desde_espn(fecha: date) -> list:
    ligas_dict = {}
    fechas_utc = [
        fecha.strftime("%Y%m%d"),
        (fecha + timedelta(days=1)).strftime("%Y%m%d"),
    ]

    async def _fetch_slug(slug: str, liga_nombre: str, pais: str):
        for fecha_str in fechas_utc:
            url = (
                f"https://site.api.espn.com/apis/site/v2/sports/soccer"
                f"/{slug}/scoreboard?dates={fecha_str}&limit=50"
            )
            try:
                async with httpx.AsyncClient(timeout=12.0, headers=HEADERS_BROWSER, follow_redirects=True) as client:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()

                for e in data.get("events", []):
                    try:
                        fecha_utc_str = e.get("date", "")
                        if not fecha_utc_str:
                            continue
                        if _utc_a_fecha_local(fecha_utc_str) != fecha:
                            continue

                        comp = (e.get("competitions") or [{}])[0]
                        competidores = comp.get("competitors", [])
                        if len(competidores) < 2:
                            continue

                        home = next((c for c in competidores if c.get("homeAway") == "home"), competidores[0])
                        away = next((c for c in competidores if c.get("homeAway") == "away"), competidores[1])
                        home_name = home.get("team", {}).get("displayName", "")
                        away_name = away.get("team", {}).get("displayName", "")
                        if not home_name or not away_name:
                            continue

                        status = comp.get("status", {})
                        status_name = status.get("type", {}).get("name", "STATUS_SCHEDULED")
                        h_score = home.get("score", "")
                        a_score = away.get("score", "")
                        resultado = f"{h_score}-{a_score}" if h_score != "" and a_score != "" and status_name != "STATUS_SCHEDULED" else ""
                        estado = {
                            "STATUS_SCHEDULED":   "⏰ Por jugar",
                            "STATUS_IN_PROGRESS": f"🔴 En vivo {status.get('displayClock','')}",
                            "STATUS_HALFTIME":    "⏸️ Entretiempo",
                            "STATUS_FINAL":       "✅ Finalizado",
                            "STATUS_FULL_TIME":   "✅ Finalizado",
                            "STATUS_POSTPONED":   "📅 Postergado",
                            "STATUS_CANCELED":    "❌ Cancelado",
                        }.get(status_name, "⏰ Por jugar")

                        if liga_nombre not in ligas_dict:
                            ligas_dict[liga_nombre] = Liga(nombre=liga_nombre, pais=pais)

                        key = f"{home_name}-{away_name}"
                        if not any(f"{p.local}-{p.visitante}" == key for p in ligas_dict[liga_nombre].partidos):
                            ligas_dict[liga_nombre].partidos.append(Partido(
                                liga=liga_nombre, pais=pais,
                                hora=_utc_a_hora_local(fecha_utc_str),
                                local=home_name, visitante=away_name,
                                resultado=resultado, estado=estado,
                            ))
                    except Exception:
                        continue
            except Exception as ex:
                logger.debug(f"ESPN/{slug}/{fecha_str}: {ex}")

    await asyncio.gather(*[_fetch_slug(s, n, p) for s, n, p in ESPN_SLUGS])
    logger.info(f"ESPN: {sum(len(l.partidos) for l in ligas_dict.values())} partidos")
    return list(ligas_dict.values())


# ── Sofascore ─────────────────────────────────────────────────────────────────

async def _desde_sofascore(fecha: date) -> list:
    fecha_str = fecha.strftime("%Y-%m-%d")
    url = f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{fecha_str}"
    headers = {**HEADERS_BROWSER, "Referer": "https://www.sofascore.com/", "Origin": "https://www.sofascore.com"}
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(f"Sofascore: {resp.status_code}")
                return []
            events = resp.json().get("events", [])
        logger.info(f"Sofascore: {len(events)} eventos")
        return _procesar_sofascore(events, fecha)
    except Exception as e:
        logger.error(f"Sofascore error: {e}")
        return []


def _procesar_sofascore(events: list, fecha: Optional[date] = None) -> list:
    ligas_dict = {}
    for e in events:
        try:
            tournament  = e.get("tournament", {})
            category    = tournament.get("category", {})
            liga_nombre = tournament.get("name", "Desconocida")
            pais        = category.get("name", "")
            home = e.get("homeTeam", {}).get("name", "")
            away = e.get("awayTeam", {}).get("name", "")
            if not home or not away:
                continue
            ts = e.get("startTimestamp")
            if not ts:
                continue
            dt_local = datetime.fromtimestamp(ts, tz=pytz.utc).astimezone(TZ_ARG)
            if fecha is not None and dt_local.date() != fecha:
                continue
            hora = dt_local.strftime("%H:%M")
            h_score = e.get("homeScore", {}).get("current")
            a_score = e.get("awayScore", {}).get("current")
            resultado = f"{h_score}-{a_score}" if h_score is not None and a_score is not None else ""
            status_code = e.get("status", {}).get("code", 0)
            if status_code == 0:
                estado = "⏰ Por jugar"
            elif status_code == 100:
                estado = "✅ Finalizado"
            elif status_code in (6, 7):
                estado = "⏸️ Entretiempo"
            elif status_code < 100:
                estado = f"🔴 En vivo {e.get('status', {}).get('description', '')}"
            else:
                estado = "⏰ Por jugar"
            key = f"{pais}-{liga_nombre}"
            if key not in ligas_dict:
                ligas_dict[key] = Liga(nombre=liga_nombre, pais=pais)
            ligas_dict[key].partidos.append(Partido(
                liga=liga_nombre, pais=pais, hora=hora,
                local=home, visitante=away,
                resultado=resultado, estado=estado,
            ))
        except Exception:
            continue
    return list(ligas_dict.values())


# ── football-data.org ─────────────────────────────────────────────────────────

async def _desde_football_data(fecha: date) -> list:
    fecha_str = fecha.strftime("%Y-%m-%d")
    url = f"https://api.football-data.org/v4/matches?dateFrom={fecha_str}&dateTo={fecha_str}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers={"X-Auth-Token": FOOTBALL_DATA_TOKEN})
            if resp.status_code != 200:
                return []
            matches = resp.json().get("matches", [])
        logger.info(f"football-data.org: {len(matches)} partidos")
        return _procesar_football_data(matches)
    except Exception as e:
        logger.error(f"football-data.org error: {e}")
        return []


def _procesar_football_data(matches: list) -> list:
    ligas_dict = {}
    for m in matches:
        try:
            comp   = m["competition"]
            area   = m.get("area", {})
            home   = m["homeTeam"].get("shortName") or m["homeTeam"]["name"]
            away   = m["awayTeam"].get("shortName") or m["awayTeam"]["name"]
            score  = m["score"]
            status = m["status"]
            hora   = _utc_a_hora_local(m.get("utcDate", ""))
            ft = score.get("fullTime", {})
            ht = score.get("halfTime", {})
            resultado = ""
            if status in ("FINISHED", "IN_PLAY", "PAUSED"):
                h = ft.get("home") if ft.get("home") is not None else ht.get("home")
                a = ft.get("away") if ft.get("away") is not None else ht.get("away")
                if h is not None and a is not None:
                    resultado = f"{h}-{a}"
            estado = {
                "SCHEDULED": "⏰ Por jugar", "TIMED": "⏰ Por jugar",
                "IN_PLAY": "🔴 En vivo", "PAUSED": "⏸️ Entretiempo",
                "FINISHED": "✅ Finalizado", "POSTPONED": "📅 Postergado",
                "CANCELLED": "❌ Cancelado",
            }.get(status, "⏰ Por jugar")
            liga_key = comp["id"]
            if liga_key not in ligas_dict:
                ligas_dict[liga_key] = Liga(nombre=comp["name"], pais=area.get("name", ""))
            ligas_dict[liga_key].partidos.append(Partido(
                liga=comp["name"], pais=area.get("name", ""),
                hora=hora, local=home, visitante=away,
                resultado=resultado, estado=estado,
            ))
        except Exception:
            continue
    return list(ligas_dict.values())


# ── Merge ─────────────────────────────────────────────────────────────────────

def _mergear(ligas_espn: list, ligas_sofa: list, ligas_fdata: list) -> list:
    nombres_vistos = set()
    ligas_finales = []
    for fuente in [ligas_espn, ligas_fdata, ligas_sofa]:
        for liga in fuente:
            key = _normalizar(liga.nombre)
            if key not in nombres_vistos:
                nombres_vistos.add(key)
                ligas_finales.append(liga)
    for liga in ligas_finales:
        liga.partidos.sort(key=lambda p: p.hora)
    ligas_finales.sort(key=lambda l: (
        0 if "argentina" in l.pais.lower() else 1,
        l.partidos[0].hora if l.partidos else "99:99",
    ))
    total = sum(len(l.partidos) for l in ligas_finales)
    logger.info(f"Total combinado: {total} partidos en {len(ligas_finales)} ligas")
    return [l for l in ligas_finales if l.partidos]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", texto.lower().strip())


def _utc_a_hora_local(fecha_utc: str) -> str:
    if not fecha_utc:
        return "--:--"
    try:
        dt = datetime.fromisoformat(re.sub(r"Z$", "+00:00", fecha_utc))
        return dt.astimezone(TZ_ARG).strftime("%H:%M")
    except Exception:
        return "--:--"


def _utc_a_fecha_local(fecha_utc: str) -> Optional[date]:
    if not fecha_utc:
        return None
    try:
        dt = datetime.fromisoformat(re.sub(r"Z$", "+00:00", fecha_utc))
        return dt.astimezone(TZ_ARG).date()
    except Exception:
        return None


def parsear_fecha(texto: str) -> Optional[date]:
    texto = texto.strip().lower()
    hoy = datetime.now(TZ_ARG).date()
    if texto in ("hoy", "today"):
        return hoy
    if texto in ("mañana", "manana", "tomorrow"):
        return hoy + timedelta(days=1)
    if texto in ("pasado", "pasado mañana", "pasado manana"):
        return hoy + timedelta(days=2)
    if texto == "ayer":
        return hoy - timedelta(days=1)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m", "%d-%m"):
        try:
            dt = datetime.strptime(texto, fmt)
            if "%Y" not in fmt:
                dt = dt.replace(year=hoy.year)
                if dt.date() < hoy - timedelta(days=1):
                    dt = dt.replace(year=hoy.year + 1)
            return dt.date()
        except ValueError:
            continue
    if texto.isdigit() and 1 <= int(texto) <= 31:
        try:
            return hoy.replace(day=int(texto))
        except ValueError:
            pass
    return None
