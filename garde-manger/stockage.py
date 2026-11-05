"""Enregistrement du placard, des courses et des réglages dans un fichier JSON.

Un seul fichier, partagé par tous les appareils qui ouvrent l'appli :
l'iPhone et l'iPad voient donc le même placard.
"""

import json
import os
import tempfile
import threading

# Taille maximale de l'état enregistré (le placard d'une famille tient en quelques Ko).
TAILLE_MAX = 1_000_000


class EtatTropGros(ValueError):
    pass


class Stockage:
    def __init__(self, chemin):
        self.chemin = chemin
        self._verrou = threading.Lock()
        os.makedirs(os.path.dirname(os.path.abspath(chemin)), exist_ok=True)

    def lire(self):
        """Renvoie (version, etat). Un fichier absent ou abîmé donne un état vide."""
        with self._verrou:
            return self._lire()

    def _lire(self):
        try:
            with open(self.chemin, encoding="utf-8") as f:
                contenu = json.load(f)
            version = int(contenu.get("version", 0))
            etat = contenu.get("etat", {})
            if not isinstance(etat, dict):
                etat = {}
            return version, etat
        except (OSError, ValueError):
            return 0, {}

    def ecrire(self, etat):
        """Remplace l'état et renvoie le nouveau numéro de version.

        Le dernier appareil qui enregistre gagne : les autres rechargent
        l'appli quand ils voient une version plus récente.
        """
        if not isinstance(etat, dict):
            raise ValueError("l'état doit être un objet JSON")
        donnees = json.dumps(etat, ensure_ascii=False)
        if len(donnees.encode("utf-8")) > TAILLE_MAX:
            raise EtatTropGros("état trop volumineux")
        with self._verrou:
            version, _ = self._lire()
            version += 1
            contenu = json.dumps({"version": version, "etat": etat}, ensure_ascii=False)
            dossier = os.path.dirname(os.path.abspath(self.chemin))
            fd, temporaire = tempfile.mkstemp(dir=dossier, prefix=".etat-", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(contenu)
                os.replace(temporaire, self.chemin)
            except BaseException:
                try:
                    os.unlink(temporaire)
                except OSError:
                    pass
                raise
            return version
