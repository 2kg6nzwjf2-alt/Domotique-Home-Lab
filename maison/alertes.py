"""Notifications des prochains jours : ménage du jour, pluie du lendemain, rendez-vous, produits à finir.

Calcul pur (sans iOS) : la liste est ensuite programmée par plateforme.NotificationsIOS.
iOS garde au plus 64 notifications par appli : on en prévoit 7 jours, 50 au plus.
"""

from datetime import date, datetime, time, timedelta

JOURS = 7
MAXIMUM = 50
SEUIL_PLUIE = 60  # % : à partir de là, on prévient la veille

# Réglages par défaut (heure "HH:MM", ou minutes avant un rendez-vous) ; "" = désactivé
DEFAUT = {"menage": "08:00", "pluie": "20:00", "rdv": "30", "peremption": "09:00"}


def reglages_valides(r):
    """Réglages de notifications nettoyés : heures HH:MM, minutes 5 à 240, ou "" (désactivé)."""
    r = r if isinstance(r, dict) else {}
    propres = {}
    for cle, defaut in DEFAUT.items():
        v = str(r.get(cle, defaut) if r.get(cle) is not None else defaut).strip()
        if cle == "rdv":
            propres[cle] = v if v.isdigit() and 5 <= int(v) <= 240 else ("" if v == "" else defaut)
        else:
            try:
                propres[cle] = time.fromisoformat(v).strftime("%H:%M") if v else ""
            except ValueError:
                propres[cle] = defaut
    return propres


def _a(jour, hhmm):
    return datetime.combine(jour, time.fromisoformat(hhmm))


def _local(iso):
    """Date ISO (avec ou sans fuseau) en heure locale de l'appareil, sans fuseau."""
    d = datetime.fromisoformat(str(iso))
    return d.astimezone().replace(tzinfo=None) if d.tzinfo else d


def _liste(noms, maxi=4):
    noms = list(dict.fromkeys(noms))
    return ", ".join(noms[:maxi]) + (f" et {len(noms) - maxi} autre{'s' if len(noms) - maxi > 1 else ''}" if len(noms) > maxi else "")


def menage(donnees, heure, maintenant):
    pieces = {p["id"]: p["nom"] for p in donnees.get("plan", {}).get("pieces", [])}
    sortie = []
    for n in range(JOURS):
        jour = maintenant.date() + timedelta(days=n)
        quand = _a(jour, heure)
        if quand <= maintenant:
            continue
        faites = set(donnees.get("fait", {}).get(jour.isoformat(), []))
        taches = [t for t in donnees.get("taches", []) if jour.weekday() in t.get("jours", []) and t.get("id") not in faites]
        if taches:
            sortie.append({"quand": quand, "titre": "Ménage du jour",
                           "message": _liste([f"{t['titre']} ({pieces.get(t['piece'], t['piece'])})" for t in taches])})
    return sortie


def pluie(meteo, heure, maintenant):
    sortie = []
    for j in (meteo or {}).get("jours", []):
        try:
            jour = date.fromisoformat(j["date"])
        except (KeyError, TypeError, ValueError):
            continue
        if (j.get("pluie") or 0) < SEUIL_PLUIE:
            continue
        quand = _a(jour - timedelta(days=1), heure)
        if quand <= maintenant:
            continue
        mm = j.get("pluie_mm")
        sortie.append({"quand": quand, "titre": "Pluie demain",
                       "message": f"{j.get('libelle', 'Pluie')} : {round(j['pluie'])} % de risque"
                                  + (f", {str(round(mm, 1)).replace('.', ',')} mm" if mm else "") + ". Pensez au parapluie."})
    return sortie


def rendez_vous(agenda, minutes, maintenant):
    sortie, vus = [], set()
    for j in (agenda or {}).get("jours", []):
        for e in j.get("evenements", []):
            if e.get("journee") or e.get("suite"):
                continue
            try:
                debut = _local(e["debut"])
            except (KeyError, TypeError, ValueError):
                continue
            quand = debut - timedelta(minutes=minutes)
            cle = (e.get("titre"), debut)
            if quand <= maintenant or cle in vus:
                continue
            vus.add(cle)
            sortie.append({"quand": quand, "titre": f"Dans {minutes} min · {debut.strftime('%H:%M')}",
                           "message": str(e.get("titre") or "Rendez-vous") + (f" — {e['lieu']}" if e.get("lieu") else "")})
    return sortie


def peremption(etat, heure, maintenant):
    par_jour = {}
    for p in (etat or {}).get("pantry", []) if isinstance((etat or {}).get("pantry"), list) else []:
        if not isinstance(p, dict) or not p.get("dlc"):
            continue
        try:
            limite = date.fromisoformat(str(p["dlc"])[:10])
        except ValueError:
            continue
        for ecart, texte in ((1, "demain"), (0, "aujourd’hui")):
            par_jour.setdefault((limite - timedelta(days=ecart), texte), []).append(str(p.get("label", ""))[:40])
    sortie = []
    for (jour, texte), noms in sorted(par_jour.items()):
        quand = _a(jour, heure)
        if maintenant < quand <= maintenant + timedelta(days=JOURS):
            sortie.append({"quand": quand, "titre": "Garde-manger", "message": f"À finir {texte} : {_liste(noms)}."})
    return sortie


def calculer(reglages, maintenant=None, menage_donnees=None, meteo=None, agenda=None, etat=None):
    """Notifications à programmer, triées par date (MAXIMUM au plus)."""
    r = reglages_valides(reglages)
    maintenant = maintenant or datetime.now()
    sortie = []
    if r["menage"] and menage_donnees:
        sortie += menage(menage_donnees, r["menage"], maintenant)
    if r["pluie"] and meteo:
        sortie += pluie(meteo, r["pluie"], maintenant)
    if r["rdv"] and agenda:
        sortie += rendez_vous(agenda, int(r["rdv"]), maintenant)
    if r["peremption"] and etat:
        sortie += peremption(etat, r["peremption"], maintenant)
    sortie.sort(key=lambda n: n["quand"])
    return sortie[:MAXIMUM]
