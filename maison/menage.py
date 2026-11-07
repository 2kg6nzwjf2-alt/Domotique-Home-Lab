"""Ménage : plan de l'appartement, tâches par pièce et par jour, tâches cochées.

Le plan est redessiné à partir du plan de l'appartement (cotes en centimètres,
arrondies) : seules les pièces et leur nom sont gardés.
Les jours vont de 0 (lundi) à 6 (dimanche).
"""

import json
import os
import re
import tempfile
import threading
import uuid
from datetime import date, timedelta

# Pièces : position et taille en centimètres (origine en haut à gauche du plan)
PLAN = {
    "largeur": 820, "hauteur": 1000, "origine": [120, 14],
    "pieces": [
        {"id": "ayami", "nom": "Ayami", "x": 434, "y": 24, "l": 236, "h": 359},
        {"id": "parent", "nom": "Parent", "x": 686, "y": 24, "l": 240, "h": 398},
        {"id": "wc", "nom": "W.C.", "x": 434, "y": 393, "l": 160, "h": 79},
        {"id": "couloir", "nom": "Couloir", "x": 610, "y": 393, "l": 160, "h": 218},
        {"id": "sdb", "nom": "Salle de bain", "x": 784, "y": 432, "l": 142, "h": 179},
        {"id": "entree", "nom": "Entrée", "x": 130, "y": 482, "l": 470, "h": 129},
        {"id": "cuisine", "nom": "Cuisine + salle à manger", "x": 255, "y": 621, "l": 671, "h": 384, "tx": 663},
    ],
    # cloison à mi-hauteur entre le coin cuisine et la salle à manger
    "traits": [[400, 621, 400, 890]],
}

# Planning de départ, modifiable dans l'appli
TACHES_DEFAUT = [
    ("cuisine", "Vaisselle et plan de travail", [0, 1, 2, 3, 4, 5, 6]),
    ("cuisine", "Sortir les poubelles", [1, 4]),
    ("cuisine", "Aspirateur", [0, 3]),
    ("cuisine", "Serpillière", [5]),
    ("cuisine", "Nettoyer le frigo", [6]),
    ("sdb", "Lavabo et miroir", [2, 5]),
    ("sdb", "Douche ou baignoire", [5]),
    ("sdb", "Changer les serviettes", [6]),
    ("wc", "Toilettes", [2, 5]),
    ("entree", "Aspirateur", [0, 3]),
    ("entree", "Ranger les chaussures", [4]),
    ("couloir", "Aspirateur", [0, 3]),
    ("parent", "Aspirateur", [0]),
    ("parent", "Poussière", [4]),
    ("parent", "Changer les draps", [6]),
    ("ayami", "Ranger la chambre", [2, 5]),
    ("ayami", "Aspirateur", [0]),
    ("ayami", "Changer les draps", [6]),
]

GARDER_JOURS = 60  # les tâches cochées plus anciennes sont oubliées
MAX_TACHES = 150


def _taches_defaut():
    return [{"id": f"t{n}", "piece": p, "titre": t, "jours": j} for n, (p, t, j) in enumerate(TACHES_DEFAUT, 1)]


def _date(texte):
    if not isinstance(texte, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", texte):
        raise ValueError("date attendue au format AAAA-MM-JJ")
    return date.fromisoformat(texte)


class Menage:
    def __init__(self, chemin, plan=None):
        self.chemin = chemin
        self.plan = plan or PLAN
        self._pieces = {p["id"] for p in self.plan["pieces"]}
        self._verrou = threading.Lock()

    def _lire(self):
        try:
            with open(self.chemin, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("taches"), list):
                d.setdefault("fait", {})
                return d
        except (OSError, ValueError):
            pass
        return {"taches": _taches_defaut(), "fait": {}}

    def _ecrire(self, d):
        dossier = os.path.dirname(os.path.abspath(self.chemin))
        os.makedirs(dossier, exist_ok=True)
        fd, temporaire = tempfile.mkstemp(dir=dossier, prefix=".menage-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(temporaire, self.chemin)

    def lire(self):
        with self._verrou:
            d = self._lire()
        return {"plan": self.plan, "taches": d["taches"], "fait": d["fait"]}

    def cocher(self, tache, jour, fait=True):
        jour = _date(jour)
        with self._verrou:
            d = self._lire()
            if tache not in {t["id"] for t in d["taches"]}:
                raise ValueError("tâche inconnue")
            cle = jour.isoformat()
            faites = set(d["fait"].get(cle, []))
            faites.add(tache) if fait else faites.discard(tache)
            d["fait"][cle] = sorted(faites)
            limite = (jour - timedelta(days=GARDER_JOURS)).isoformat()
            d["fait"] = {k: v for k, v in d["fait"].items() if v and k >= limite}
            self._ecrire(d)
            return d["fait"].get(cle, [])

    def enregistrer_taches(self, taches):
        if not isinstance(taches, list):
            raise ValueError("liste de tâches attendue")
        propres = []
        for t in taches[:MAX_TACHES]:
            if not isinstance(t, dict):
                continue
            titre = str(t.get("titre") or "").strip()[:80]
            piece = str(t.get("piece") or "")
            jours = sorted({int(j) for j in t.get("jours") or [] if str(j).isdigit() and 0 <= int(j) <= 6})
            if not titre or piece not in self._pieces or not jours:
                continue
            identifiant = str(t.get("id") or "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", identifiant):
                identifiant = "t" + uuid.uuid4().hex[:10]
            propres.append({"id": identifiant, "piece": piece, "titre": titre, "jours": jours})
        with self._verrou:
            d = self._lire()
            d["taches"] = propres
            ids = {t["id"] for t in propres}
            d["fait"] = {k: [i for i in v if i in ids] for k, v in d["fait"].items()}
            self._ecrire(d)
        return propres
