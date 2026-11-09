"""Liens entre les fonctions : ce que l'agenda change pour Garde-manger, etc."""

import re
from datetime import date, datetime, time, timedelta

# Un rendez-vous qui contient un de ces mots est un repas pris dehors.
REPAS_DEHORS = re.compile(r"\b(d[îi]ner|d[ée]jeuner du soir|resto|restaurant|ap[ée]ro|barbecue|pique-nique|mariage|f[êe]te)\b", re.I)
DEBUT_SOIREE, FIN_SOIREE = time(18, 0), time(21, 30)


def soiree(evenements, maintenant=None):
    """Repère un repas dehors ou une soirée chargée dans les rendez-vous du jour.

    Renvoie None, ou {"type": "dehors" | "charge", "titre", "heure"}.
    """
    candidats = []
    for e in evenements or []:
        if e.get("journee"):
            continue
        try:
            debut = datetime.fromisoformat(e["debut"])
            fin = datetime.fromisoformat(e["fin"]) if e.get("fin") else debut + timedelta(hours=1)
        except (KeyError, TypeError, ValueError):
            continue
        maintenant_ici = maintenant or datetime.now(debut.tzinfo)
        bornes = (datetime.combine(debut.date(), DEBUT_SOIREE, debut.tzinfo), datetime.combine(debut.date(), FIN_SOIREE, debut.tzinfo))
        if fin <= bornes[0] or debut >= bornes[1] or fin <= maintenant_ici:
            continue
        candidats.append((bool(REPAS_DEHORS.search(e.get("titre", ""))), debut, e.get("titre", "")))
    if not candidats:
        return None
    dehors = [c for c in candidats if c[0]]
    choisi = min(dehors or candidats, key=lambda c: c[1])
    return {"type": "dehors" if dehors else "charge", "titre": choisi[2], "heure": choisi[1].strftime("%H:%M")}


def repartir_par_jour(evenements, debut, nombre=7, fuseau=None):
    """Range les événements dans les jours qu'ils occupent, de `debut` (date) à `debut + nombre` jours.

    Un événement sur plusieurs jours apparaît chaque jour, avec "suite": True après le premier.
    Renvoie [{"jour": "AAAA-MM-JJ", "evenements": [...]}, ...].
    """
    jours = [{"jour": (debut + timedelta(days=n)).isoformat(), "evenements": []} for n in range(nombre)]
    for e in evenements or []:
        try:
            if e.get("journee"):
                premier = date.fromisoformat(str(e["debut"])[:10])
                dernier = date.fromisoformat(str(e["fin"])[:10]) - timedelta(days=1) if e.get("fin") else premier
            else:
                d = datetime.fromisoformat(e["debut"])
                f = datetime.fromisoformat(e["fin"]) if e.get("fin") else d
                if fuseau is not None:
                    d, f = d.astimezone(fuseau), f.astimezone(fuseau)
                premier = d.date()
                dernier = max(premier, (f - timedelta(microseconds=1)).date())
        except (KeyError, TypeError, ValueError):
            continue
        for n in range(nombre):
            jour = debut + timedelta(days=n)
            if premier <= jour <= dernier:
                jours[n]["evenements"].append({**e, "suite": jour != premier} if jour != premier else e)
    for j in jours:
        j["evenements"].sort(key=lambda e: (not e.get("journee"), e.get("suite", False) is False, str(e.get("debut"))))
    return jours
