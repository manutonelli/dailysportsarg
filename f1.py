"""
Módulo de Fórmula 1.
Fuente: Jolpica F1 API (reemplazo oficial de Ergast, misma estructura, gratuita)
        https://api.jolpi.ca/ergast/f1/
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import httpx
import pytz

logger = logging.getLogger(__name__)

TZ_ARG = pytz.timezone("America/Argentina/Buenos_Aires")
BASE = "https://api.jolpi.ca/ergast/f1"


@dataclass
class SesionF1:
    nombre: str
    hora_local: str
    tipo: str   # "practice" | "qualifying" | "sprint" | "race"


@dataclass
class EventoF1:
    gran_premio: str
    circuito: str
    pais: str
    ciudad: str
    ronda: int
    temporada: int
    sesiones_hoy: list = field(default_factory=list)

    @property
    def es_dia_de_carrera(self):
        return any(s.tipo == "race" for s in self.sesiones_hoy)


async def obtener_evento_f1_hoy() -> Optional[EventoF1]:
    try:
        año = datetime.now(TZ_ARG).year
        races = await _get_schedule(año)
        if not races:
            return None
        hoy = datetime.now(TZ_ARG).date()
        return _buscar_evento_hoy(races, hoy)
    except Exception as e:
        logger.error(f"Error obteniendo evento F1: {e}")
        return None


async def obtener_proxima_carrera() -> Optional[EventoF1]:
    try:
        año = datetime.now(TZ_ARG).year
        races = await _get_schedule(año)
        hoy = datetime.now(TZ_ARG).date()
        for race in races:
            fecha = _parse_fecha(race.get("date"), race.get("time"))
            if fecha and fecha.astimezone(TZ_ARG).date() >= hoy:
                circuito = race.get("Circuit", {})
                ubicacion = circuito.get("Location", {})
                sesiones = _todas_las_sesiones(race, fecha)
                return EventoF1(
                    gran_premio=race.get("raceName", "Gran Premio"),
                    circuito=circuito.get("circuitName", ""),
                    pais=ubicacion.get("country", ""),
                    ciudad=ubicacion.get("locality", ""),
                    ronda=int(race.get("round", 0)),
                    temporada=int(race.get("season", año)),
                    sesiones_hoy=sesiones,
                )
    except Exception as e:
        logger.error(f"Error obteniendo próxima carrera: {e}")
    return None


async def _get_schedule(año: int) -> list:
    url = f"{BASE}/{año}.json?limit=30"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        return data["MRData"]["RaceTable"]["Races"]
    except Exception as e:
        logger.error(f"Jolpica F1 API error: {e}")
        return []


def _buscar_evento_hoy(races: list, hoy: date) -> Optional[EventoF1]:
    mapeo = {
        "FirstPractice":    ("Práctica Libre 1", "practice"),
        "SecondPractice":   ("Práctica Libre 2", "practice"),
        "ThirdPractice":    ("Práctica Libre 3", "practice"),
        "Qualifying":       ("Clasificación",    "qualifying"),
        "Sprint":           ("Sprint",            "sprint"),
        "SprintShootout":   ("Sprint Shootout",   "sprint"),
        "SprintQualifying": ("Sprint Qualifying", "sprint"),
    }
    for race in races:
        fecha_carrera = _parse_fecha(race.get("date"), race.get("time"))
        if not fecha_carrera:
            continue

        sesiones_hoy = []

        for key, (nombre, tipo) in mapeo.items():
            bloque = race.get(key)
            if bloque:
                dt = _parse_fecha(bloque.get("date"), bloque.get("time"))
                if dt and dt.astimezone(TZ_ARG).date() == hoy:
                    sesiones_hoy.append(SesionF1(
                        nombre=nombre,
                        hora_local=dt.astimezone(TZ_ARG).strftime("%H:%M"),
                        tipo=tipo,
                    ))

        if fecha_carrera.astimezone(TZ_ARG).date() == hoy:
            sesiones_hoy.append(SesionF1(
                nombre="🏁 CARRERA",
                hora_local=fecha_carrera.astimezone(TZ_ARG).strftime("%H:%M"),
                tipo="race",
            ))

        if not sesiones_hoy:
            continue

        circuito = race.get("Circuit", {})
        ubicacion = circuito.get("Location", {})
        return EventoF1(
            gran_premio=race.get("raceName", "Gran Premio"),
            circuito=circuito.get("circuitName", ""),
            pais=ubicacion.get("country", ""),
            ciudad=ubicacion.get("locality", ""),
            ronda=int(race.get("round", 0)),
            temporada=int(race.get("season", datetime.now().year)),
            sesiones_hoy=sorted(sesiones_hoy, key=lambda s: s.hora_local),
        )
    return None


def _todas_las_sesiones(race: dict, fecha_carrera: datetime) -> list:
    mapeo = {
        "FirstPractice":    ("Práctica Libre 1", "practice"),
        "SecondPractice":   ("Práctica Libre 2", "practice"),
        "ThirdPractice":    ("Práctica Libre 3", "practice"),
        "Qualifying":       ("Clasificación",    "qualifying"),
        "Sprint":           ("Sprint",            "sprint"),
        "SprintShootout":   ("Sprint Shootout",   "sprint"),
        "SprintQualifying": ("Sprint Qualifying", "sprint"),
    }
    sesiones = []
    for key, (nombre, tipo) in mapeo.items():
        bloque = race.get(key)
        if bloque:
            dt = _parse_fecha(bloque.get("date"), bloque.get("time"))
            if dt:
                sesiones.append(SesionF1(
                    nombre=nombre,
                    hora_local=dt.astimezone(TZ_ARG).strftime("%a %d/%m %H:%M"),
                    tipo=tipo,
                ))
    sesiones.append(SesionF1(
        nombre="🏁 CARRERA",
        hora_local=fecha_carrera.astimezone(TZ_ARG).strftime("%a %d/%m %H:%M"),
        tipo="race",
    ))
    return sesiones


def _parse_fecha(fecha_str, hora_str) -> Optional[datetime]:
    if not fecha_str:
        return None
    try:
        hora_clean = re.sub(r"Z$", "", hora_str) if hora_str else "12:00:00"
        return datetime.fromisoformat(f"{fecha_str}T{hora_clean}+00:00")
    except Exception:
        return None
