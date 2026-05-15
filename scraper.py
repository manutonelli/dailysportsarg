"""
Scraper de partidos de fútbol.
Fuente principal: Promiedos.com.ar (API interna Next.js)
Fallback: ESPN API pública
"""

import asyncio
import logging
import re
from datetime import date, datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional
import os

import httpx
import pytz

logger = logging.getLogger(__name__)

TZ_ARG = pytz.timezone("America/Argentina/Buenos_Aires")

HEADERS_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    "Referer": "https://www.promiedos.com.ar/",
}

FOOTBALL_DATA_TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN", "")

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
    ("mex.1",                 "Liga MX",              "México"),
    ("bra.1",                 "Brasileirao",          "Brasil"),
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


# ── Función principal ─────────────────────────────────────────────────────────

async def obtener_partidos(fecha: Optional[date] = None) -> list:
    if fecha is None:
        fecha = datetime.now(TZ_ARG).date()

    # Promiedos es la fuente principal
    ligas_promiedos = await _desde_promiedos(fecha)

    if ligas_promiedos:
        logger.info(f"Usando Promiedos: {sum(len(l.partidos) for l in ligas_promiedos)} partidos")
        return _ordenar(ligas_promiedos)

    # Fallback: ESPN + football-data.org
    logger.warning("Promiedos falló, usando fallback ESPN")
    resultados = await asyncio.gather(
        _desde_espn(fecha),
        _desde_football_data(fecha) if FOOTBALL_DATA_TOKEN else _vacio(),
        return_exceptions=True,
    )
    ligas_espn   = resultados[0] if isinstance(resultados[0], list) else []
    ligas_fdata  = resultados[1] if isinstance(resultados[1], list) else []
    return _mergear(ligas_espn, ligas_fdata)


async def _vacio():
    return []


# ── Promiedos ─────────────────────────────────────────────────────────────────

async def _desde_promiedos(fecha: date) -> list:
    try:
        async with httpx.AsyncClient(
            timeout=15.0, headers=HEADERS_BROWSER, follow_redirects=True
        ) as client:
            # 1. Obtener buildId
            resp = await client.get("https://www.promiedos.com.ar/")
            if resp.status_code != 200:
                logger.error(f"Promiedos home: {resp.status_code}")
                return []

            build_match = re.search(r'"buildId":"([^"]+)"', resp.text)
            if not build_match:
                logger.error("Promiedos: no se encontró buildId")
                return []
            build_id = build_match.group(1)

            # 2. Si no es hoy, usar endpoint de fecha
            hoy = datetime.now(TZ_ARG).date()
            if fecha == hoy:
                data_url = f"https://www.promiedos.com.ar/_next/data/{build_id}/index.json"
            else:
                fecha_str = fecha.strftime("%d-%m-%Y")
                data_url = f"https://www.promiedos.com.ar/_next/data/{build_id}/fecha/{fecha_str}.json"

            data_resp = await client.get(data_url)

            # Si falla el endpoint de fecha, intentar con el index y filtrar
            if data_resp.status_code != 200:
                logger.warning(f"Promiedos fecha URL falló ({data_resp.status_code}), usando index")
                data_url = f"https://www.promiedos.com.ar/_next/data/{build_id}/index.json"
                data_resp = await client.get(data_url)
                if data_resp.status_code != 200:
                    return []

            data = data_resp.json()

        leagues = data.get("pageProps", {}).get("data", {}).get("leagues", [])
        logger.info(f"Promiedos: {len(leagues)} ligas encontradas")
        return _procesar_promiedos(leagues)

    except Exception as e:
        logger.error(f"Error Promiedos: {e}")
        return []


def _procesar_promiedos(leagues: list) -> list:
    ligas_dict = {}

    # Estados de Promiedos
    ESTADOS = {
        1: "⏰ Por jugar",
        2: "🔴 En vivo",
        3: "⏸️ Entretiempo",
        4: "✅ Finalizado",
        5: "✅ Finalizado",
        6: "📅 Postergado",
        7: "❌ Suspendido",
    }

    # Palabras para filtrar ligas no deseadas
    EXCLUIR = {"femenino", "femenina", "(f)", "sub-", "u17", "u20", "reserva"}

    for liga_data in leagues:
        nombre = liga_data.get("name", "")
        pais   = liga_data.get("country_name", "")

        # Filtrar ligas no deseadas
        nombre_lower = nombre.lower()
        if any(ex in nombre_lower for ex in EXCLUIR):
            continue

        for game in liga_data.get("games", []):
            try:
                teams = game.get("teams", [])
                if len(teams) < 2:
                    continue

                local    = teams[0].get("name", "")
                visitante = teams[1].get("name", "")
                if not local or not visitante:
                    continue

                # Hora — viene como "DD-MM-YYYY HH:MM"
                start_time = game.get("start_time", "")
                hora = "--:--"
                if start_time and " " in start_time:
                    hora = start_time.split(" ")[1][:5]

                # Estado
                status_enum = game.get("status", {}).get("enum", 1)
                estado = ESTADOS.get(status_enum, "⏰ Por jugar")

                # Minuto en vivo
                if status_enum in (2, 3):
                    minuto = game.get("game_time_to_display", "")
                    if minuto:
                        estado = f"🔴 En vivo {minuto}"

                # Resultado
                score_local    = teams[0].get("score")
                score_visitante = teams[1].get("score")
                resultado = ""
                if score_local is not None and score_visitante is not None:
                    resultado = f"{score_local}-{score_visitante}"

                key = f"{pais}-{nombre}"
                if key not in ligas_dict:
                    ligas_dict[key] = Liga(nombre=nombre, pais=pais)

                ligas_dict[key].partidos.append(Partido(
                    liga=nombre, pais=pais, hora=hora,
                    local=local, visitante=visitante,
                    resultado=resultado, estado=estado,
                ))
            except Exception:
                continue

    return list(ligas_dict.values())


# ── ESPN (fallback) ───────────────────────────────────────────────────────────

async def _desde_espn(fecha: date) -> list:
    ligas_dict = {}
    fechas_utc = [fecha.strftime("%Y%m%d"), (fecha + timedelta(days=1)).strftime("%Y%m%d")]

    async def _fetch_slug(slug: str, liga_nombre: str, pais: str):
        for fecha_str in fechas_utc:
            url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard?dates={fecha_str}&limit=50"
            try:
                async with httpx.AsyncClient(timeout=12.0, headers=HEADERS_BROWSER, follow_redirects=True) as client:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                for e in data.get("events", []):
                    try:
                        fecha_utc_str = e.get("date", "")
                        if not fecha_utc_str or _utc_a_fecha_local(fecha_utc_str) != fecha:
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
                            "STATUS_SCHEDULED": "⏰ Por jugar",
                            "STATUS_IN_PROGRESS": f"🔴 En vivo {status.get('displayClock','')}",
                            "STATUS_HALFTIME": "⏸️ Entretiempo",
                            "STATUS_FINAL": "✅ Finalizado",
                            "STATUS_FULL_TIME": "✅ Finalizado",
                            "STATUS_POSTPONED": "📅 Postergado",
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
                logger.debug(f"ESPN/{slug}: {ex}")

    await asyncio.gather(*[_fetch_slug(s, n, p) for s, n, p in ESPN_SLUGS])
    logger.info(f"ESPN: {sum(len(l.partidos) for l in ligas_dict.values())} partidos")
    return list(ligas_dict.values())


# ── football-data.org (fallback) ──────────────────────────────────────────────

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
        logger.error(f"football-data.org: {e}")
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


# ── Merge y ordenamiento ──────────────────────────────────────────────────────

def _mergear(ligas_a: list, ligas_b: list) -> list:
    nombres_vistos = set()
    ligas_finales = []
    for fuente in [ligas_a, ligas_b]:
        for liga in fuente:
            key = _normalizar(liga.nombre)
            if key not in nombres_vistos:
                nombres_vistos.add(key)
                ligas_finales.append(liga)
    return _ordenar(ligas_finales)


def _ordenar(ligas: list) -> list:
    for liga in ligas:
        liga.partidos.sort(key=lambda p: p.hora)
    ligas.sort(key=lambda l: (
        0 if "argentina" in l.pais.lower() else 1,
        l.partidos[0].hora if l.partidos else "99:99",
    ))
    total = sum(len(l.partidos) for l in ligas)
    logger.info(f"Total: {total} partidos en {len(ligas)} ligas")
    return [l for l in ligas if l.partidos]


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
