"""Agenda du jour et des 7 prochains jours, lu depuis l'adresse secrète iCal de Google Agenda (lecture seule).

Google Agenda > Paramètres > (votre agenda) > Intégrer l'agenda >
« Adresse secrète au format iCal ». Plusieurs adresses peuvent être données,
séparées par des espaces ou des virgules.
"""

import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events
import requests

from liens import repartir_par_jour

DUREE_CACHE = 300  # secondes


class Agenda:
    def __init__(self, adresses, fuseau="Europe/Paris", session=None):
        self.adresses = [a for a in adresses if a]
        self.fuseau = ZoneInfo(fuseau)
        self.session = session or requests.Session()
        self._cache = {}
        self._verrou = threading.Lock()

    @classmethod
    def depuis_texte(cls, texte, fuseau="Europe/Paris"):
        adresses = [a.strip() for a in (texte or "").replace(",", " ").split()]
        return cls(adresses, fuseau) if any(adresses) else None

    def _calendrier(self, adresse):
        with self._verrou:
            en_cache = self._cache.get(adresse)
            if en_cache and time.monotonic() - en_cache[0] < DUREE_CACHE:
                return en_cache[1]
        reponse = self.session.get(adresse, timeout=15)
        reponse.raise_for_status()
        calendrier = icalendar.Calendar.from_ical(reponse.content)
        with self._verrou:
            self._cache[adresse] = (time.monotonic(), calendrier)
        return calendrier

    def _heure(self, valeur):
        if isinstance(valeur, datetime):
            if valeur.tzinfo is None:
                valeur = valeur.replace(tzinfo=self.fuseau)
            return valeur.astimezone(self.fuseau)
        return valeur

    def du_jour(self, jour=None):
        jour = jour or datetime.now(self.fuseau).date()
        evenements, erreurs = self._entre(jour, jour + timedelta(days=1))
        return {"jour": jour.isoformat(), "evenements": evenements, "erreurs": erreurs}

    def semaine(self, debut=None, nombre=7):
        debut = debut or datetime.now(self.fuseau).date()
        evenements, erreurs = self._entre(debut, debut + timedelta(days=nombre))
        return {"debut": debut.isoformat(), "jours": repartir_par_jour(evenements, debut, nombre, self.fuseau), "erreurs": erreurs}

    def _entre(self, debut, fin):
        """Événements entre deux dates (fin exclue), tous agendas confondus, et erreurs de lecture."""
        evenements, erreurs = [], []
        for numero, adresse in enumerate(self.adresses, start=1):
            try:
                calendrier = self._calendrier(adresse)
            except (requests.RequestException, ValueError) as e:
                # l'adresse est secrète : elle n'apparaît jamais dans le message
                statut = getattr(getattr(e, "response", None), "status_code", None)
                erreurs.append(f"Agenda {numero} illisible" + (f" (erreur {statut})" if statut else ""))
                continue
            nom = str(calendrier.get("X-WR-CALNAME", "") or f"Agenda {numero}")
            for ev in recurring_ical_events.of(calendrier).between(debut, fin):
                if str(ev.get("STATUS", "")).upper() == "CANCELLED":
                    continue
                debut = self._heure(ev.decoded("DTSTART"))
                fin = self._heure(ev.decoded("DTEND")) if ev.get("DTEND") else None
                journee = not isinstance(debut, datetime)
                if journee and fin is None:
                    fin = debut + timedelta(days=1)
                evenements.append({
                    "titre": str(ev.get("SUMMARY", "") or "(sans titre)")[:200],
                    "lieu": str(ev.get("LOCATION", "") or "")[:200],
                    "debut": debut.isoformat(),
                    "fin": fin.isoformat() if fin else None,
                    "journee": journee,
                    "agenda": nom,
                })
        evenements.sort(key=lambda e: (not e["journee"], e["debut"]))
        return evenements, erreurs
