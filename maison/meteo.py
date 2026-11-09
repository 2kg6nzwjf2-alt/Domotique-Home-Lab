"""Météo d'aujourd'hui et de demain, et prévisions heure par heure sur 7 jours, par Open-Meteo (gratuit, sans clé ni compte).

https://open-meteo.com — données utilisables gratuitement pour un usage non commercial.
"""

import threading
import time

import requests

GEOCODAGE = "https://geocoding-api.open-meteo.com/v1/search"
PREVISIONS = "https://api.open-meteo.com/v1/forecast"
DUREE_CACHE = 1800  # 30 minutes

# Codes météo WMO -> (libellé, icône)
CODES = {
    0: ("Ensoleillé", "soleil"), 1: ("Plutôt ensoleillé", "soleil"), 2: ("Éclaircies", "eclaircie"), 3: ("Couvert", "nuage"),
    45: ("Brouillard", "brouillard"), 48: ("Brouillard givrant", "brouillard"),
    51: ("Bruine légère", "pluie"), 53: ("Bruine", "pluie"), 55: ("Bruine forte", "pluie"),
    56: ("Bruine verglaçante", "pluie"), 57: ("Bruine verglaçante", "pluie"),
    61: ("Pluie faible", "pluie"), 63: ("Pluie", "pluie"), 65: ("Forte pluie", "pluie"),
    66: ("Pluie verglaçante", "pluie"), 67: ("Pluie verglaçante", "pluie"),
    71: ("Neige faible", "neige"), 73: ("Neige", "neige"), 75: ("Forte neige", "neige"), 77: ("Grains de neige", "neige"),
    80: ("Averses", "pluie"), 81: ("Averses", "pluie"), 82: ("Fortes averses", "pluie"),
    85: ("Averses de neige", "neige"), 86: ("Averses de neige", "neige"),
    95: ("Orage", "orage"), 96: ("Orage avec grêle", "orage"), 99: ("Orage avec grêle", "orage"),
}


class ErreurMeteo(Exception):
    pass


def decrire(code):
    try:
        return CODES.get(int(code), ("Temps inconnu", "nuage"))
    except (TypeError, ValueError):
        return ("Temps inconnu", "nuage")


class Meteo:
    def __init__(self, ville, session=None):
        self.ville = str(ville or "").strip()
        self.session = session or requests.Session()
        self._lieu = None
        self._cache = None
        self._cache_semaine = None
        self._verrou = threading.Lock()

    @classmethod
    def depuis_texte(cls, ville):
        return cls(ville) if str(ville or "").strip() else None

    def _json(self, url, params):
        try:
            r = self.session.get(url, params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            raise ErreurMeteo(f"Météo injoignable ({type(e).__name__})") from e

    def lieu(self):
        if self._lieu is None:
            d = self._json(GEOCODAGE, {"name": self.ville, "count": 1, "language": "fr", "format": "json"})
            resultats = d.get("results") or []
            if not resultats:
                raise ErreurMeteo(f"Ville « {self.ville} » introuvable. Essayez avec le code postal ou une grande ville proche.")
            r = resultats[0]
            self._lieu = {"nom": r.get("name") or self.ville, "lat": r["latitude"], "lon": r["longitude"]}
        return self._lieu

    def previsions(self):
        with self._verrou:
            if self._cache and time.monotonic() - self._cache[0] < DUREE_CACHE:
                return self._cache[1]
            lieu = self.lieu()
            d = self._json(PREVISIONS, {
                "latitude": lieu["lat"], "longitude": lieu["lon"], "timezone": "auto", "forecast_days": 2,
                "current": "temperature_2m,weather_code",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
            })
            jours = []
            quotidien = d.get("daily") or {}
            for i, date in enumerate((quotidien.get("time") or [])[:2]):
                valeur = lambda cle: (quotidien.get(cle) or [None] * 2)[i]  # noqa: E731
                libelle, icone = decrire(valeur("weather_code"))
                jours.append({"date": date, "libelle": libelle, "icone": icone,
                              "min": valeur("temperature_2m_min"), "max": valeur("temperature_2m_max"),
                              "pluie": valeur("precipitation_probability_max"),
                              "lever": str(valeur("sunrise") or "")[11:16], "coucher": str(valeur("sunset") or "")[11:16]})
            actuel = d.get("current") or {}
            libelle, icone = decrire(actuel.get("weather_code"))
            resultat = {"lieu": lieu["nom"], "jours": jours,
                        "maintenant": {"temperature": actuel.get("temperature_2m"), "libelle": libelle, "icone": icone}}
            self._cache = (time.monotonic(), resultat)
            return resultat

    def semaine(self):
        """Prévisions des 7 prochains jours, avec le détail heure par heure de chaque jour."""
        with self._verrou:
            if self._cache_semaine and time.monotonic() - self._cache_semaine[0] < DUREE_CACHE:
                return self._cache_semaine[1]
            lieu = self.lieu()
            d = self._json(PREVISIONS, {
                "latitude": lieu["lat"], "longitude": lieu["lon"], "timezone": "auto", "forecast_days": 7,
                "wind_speed_unit": "kmh",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
                         "precipitation_sum,wind_speed_10m_max,wind_gusts_10m_max,uv_index_max,sunrise,sunset",
                "hourly": "temperature_2m,apparent_temperature,weather_code,precipitation_probability,precipitation,wind_speed_10m",
            })
            horaire = d.get("hourly") or {}
            heures = {}
            for i, moment in enumerate(horaire.get("time") or []):
                valeur = lambda cle: _a(horaire, cle, i)  # noqa: E731
                libelle, icone = decrire(valeur("weather_code"))
                heures.setdefault(str(moment)[:10], []).append({
                    "heure": str(moment)[11:16], "temperature": valeur("temperature_2m"), "ressenti": valeur("apparent_temperature"),
                    "libelle": libelle, "icone": icone, "pluie": valeur("precipitation_probability"),
                    "pluie_mm": valeur("precipitation"), "vent": valeur("wind_speed_10m")})
            quotidien = d.get("daily") or {}
            jours = []
            for i, date in enumerate(quotidien.get("time") or []):
                valeur = lambda cle: _a(quotidien, cle, i)  # noqa: E731
                libelle, icone = decrire(valeur("weather_code"))
                jours.append({"date": date, "libelle": libelle, "icone": icone,
                              "min": valeur("temperature_2m_min"), "max": valeur("temperature_2m_max"),
                              "pluie": valeur("precipitation_probability_max"), "pluie_mm": valeur("precipitation_sum"),
                              "vent": valeur("wind_speed_10m_max"), "rafales": valeur("wind_gusts_10m_max"),
                              "uv": valeur("uv_index_max"),
                              "lever": str(valeur("sunrise") or "")[11:16], "coucher": str(valeur("sunset") or "")[11:16],
                              "heures": heures.get(date, [])})
            resultat = {"lieu": lieu["nom"], "jours": jours}
            self._cache_semaine = (time.monotonic(), resultat)
            return resultat


def _a(series, cle, i):
    """i-ème valeur d'une série Open-Meteo, ou None si elle manque."""
    valeurs = series.get(cle) or []
    return valeurs[i] if i < len(valeurs) else None
