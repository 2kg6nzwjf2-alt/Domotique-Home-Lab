"""Rappels Apple (tâches, courses…) envoyés par le Raccourci de l'iPhone.

Apple ne permet à aucun service extérieur de lire l'appli Rappels. Un Raccourci
sur l'iPhone envoie donc les rappels non terminés au serveur, une ligne par rappel :

    Liste | Titre | Échéance

L'échéance est facultative (format ISO 8601, par exemple 2026-11-05T18:00:00+01:00).
"""

import json
import os
import tempfile
import threading
from datetime import datetime, timezone

MAX_RAPPELS = 500


def _date(texte):
    texte = (texte or "").strip()
    if not texte:
        return None, False
    try:
        valeur = datetime.fromisoformat(texte.replace("Z", "+00:00"))
    except ValueError:
        return None, False
    # « 2026-11-05 » sans heure : rappel pour la journée
    return valeur.isoformat(), len(texte) <= 10


def analyser_texte(texte):
    """Lit le texte envoyé par le Raccourci et renvoie la liste des rappels."""
    rappels = []
    for ligne in str(texte or "").splitlines():
        if not ligne.strip():
            continue
        morceaux = [m.strip() for m in ligne.split("|")]
        if len(morceaux) == 1:
            liste, titre, echeance = "Rappels", morceaux[0], ""
        elif len(morceaux) == 2:
            liste, titre, echeance = morceaux[0], morceaux[1], ""
        else:
            # un « | » dans le titre est conservé : seuls le premier et le dernier champ sont séparés
            liste, titre, echeance = morceaux[0], " | ".join(morceaux[1:-1]), morceaux[-1]
            if echeance and _date(echeance)[0] is None:
                titre, echeance = f"{titre} | {echeance}", ""
        if not titre:
            continue
        rappels.append(_rappel(liste, titre, echeance))
        if len(rappels) >= MAX_RAPPELS:
            break
    return rappels


def analyser_json(donnees):
    """Accepte aussi {"rappels": [{"liste", "titre", "echeance"}]}."""
    elements = donnees.get("rappels") if isinstance(donnees, dict) else donnees
    if not isinstance(elements, list):
        raise ValueError("liste de rappels attendue")
    rappels = []
    for e in elements[:MAX_RAPPELS]:
        if isinstance(e, dict) and str(e.get("titre") or "").strip():
            rappels.append(_rappel(e.get("liste"), e.get("titre"), e.get("echeance")))
    return rappels


def _rappel(liste, titre, echeance):
    date, journee = _date(echeance if isinstance(echeance, str) else "")
    return {
        "liste": (str(liste or "").strip() or "Rappels")[:60],
        "titre": str(titre).strip()[:200],
        "echeance": date,
        "journee": journee,
    }


class Rappels:
    def __init__(self, chemin):
        self.chemin = chemin
        self._verrou = threading.Lock()
        os.makedirs(os.path.dirname(os.path.abspath(chemin)), exist_ok=True)

    def lire(self):
        try:
            with open(self.chemin, encoding="utf-8") as f:
                contenu = json.load(f)
            if isinstance(contenu, dict) and isinstance(contenu.get("rappels"), list):
                return contenu
        except (OSError, ValueError):
            pass
        return {"recu": None, "rappels": []}

    def enregistrer(self, rappels):
        contenu = {"recu": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rappels": rappels}
        dossier = os.path.dirname(os.path.abspath(self.chemin))
        with self._verrou:
            fd, temporaire = tempfile.mkstemp(dir=dossier, prefix=".rappels-", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(contenu, f, ensure_ascii=False)
            os.replace(temporaire, self.chemin)
        return contenu
