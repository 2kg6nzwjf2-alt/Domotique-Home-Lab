"""Enregistrement du placard, des courses et des réglages dans un fichier JSON.

Un seul fichier, partagé par tous les appareils qui ouvrent l'appli :
l'iPhone et l'iPad voient donc le même placard.
"""

import json
import os
import tempfile
import threading
from datetime import datetime, timezone

# Taille maximale de l'état enregistré (le placard d'une famille tient en quelques Ko).
TAILLE_MAX = 1_000_000


class EtatTropGros(ValueError):
    pass


class VersionDepassee(ValueError):
    """Un autre appareil a enregistré entre-temps : l'appareil doit recharger avant d'écrire."""

    def __init__(self, version):
        super().__init__("le placard a été modifié sur un autre appareil")
        self.version = version


class EnAttenteICloud(OSError):
    """Le fichier est dans iCloud mais pas encore téléchargé sur cet appareil."""


def fantome_icloud(chemin):
    """Vrai si le fichier n'existe sur cet appareil que sous forme de « .nom.icloud » (pas encore téléchargé)."""
    dossier, nom = os.path.split(os.path.abspath(chemin))
    return not os.path.exists(chemin) and os.path.exists(os.path.join(dossier, f".{nom}.icloud"))


class Stockage:
    """`avant_lecture(chemin)` : appelée avant chaque lecture (version Pythonista : téléchargement depuis iCloud).
    `appareil` : nom de l'appareil, noté à chaque enregistrement (« iPhone », « iPad »)."""

    def __init__(self, chemin, avant_lecture=None, appareil=None):
        self.chemin = chemin
        self.avant_lecture, self.appareil = avant_lecture, appareil
        self._verrou = threading.Lock()
        os.makedirs(os.path.dirname(os.path.abspath(chemin)), exist_ok=True)

    def _rafraichir(self):
        if self.avant_lecture is not None:
            try:
                self.avant_lecture(self.chemin)
            except Exception:  # iCloud indisponible : on lit la copie locale
                pass

    def lire(self):
        """Renvoie (version, etat). Un fichier absent ou abîmé donne un état vide."""
        with self._verrou:
            self._rafraichir()
            return self._lire()[:2]

    def infos(self):
        """Version, appareil et date du dernier enregistrement, et si le fichier attend iCloud."""
        with self._verrou:
            self._rafraichir()
            version, _, contenu = self._lire()
            return {"version": version, "appareil": contenu.get("appareil"), "date": contenu.get("date"),
                    "en_attente": fantome_icloud(self.chemin)}

    def _lire(self):
        try:
            with open(self.chemin, encoding="utf-8") as f:
                contenu = json.load(f)
            version = int(contenu.get("version", 0))
            etat = contenu.get("etat", {})
            if not isinstance(etat, dict):
                etat = {}
            return version, etat, contenu
        except (OSError, ValueError, AttributeError):
            return 0, {}, {}

    def ecrire(self, etat, base=None):
        """Remplace l'état et renvoie le nouveau numéro de version.

        `base` : version que l'appareil avait chargée. Si un autre appareil a enregistré
        depuis, VersionDepassee est levée et rien n'est écrit (l'appareil recharge).
        Sans `base`, le dernier qui enregistre gagne.
        """
        if not isinstance(etat, dict):
            raise ValueError("l'état doit être un objet JSON")
        donnees = json.dumps(etat, ensure_ascii=False)
        if len(donnees.encode("utf-8")) > TAILLE_MAX:
            raise EtatTropGros("état trop volumineux")
        with self._verrou:
            self._rafraichir()
            if fantome_icloud(self.chemin):
                # écrire maintenant effacerait le placard enregistré par l'autre appareil
                raise EnAttenteICloud("placard pas encore téléchargé depuis iCloud")
            version, _, _ = self._lire()
            if base is not None and base < version:
                raise VersionDepassee(version)
            version += 1
            contenu = {"version": version, "etat": etat, "date": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            if self.appareil:
                contenu["appareil"] = self.appareil
            dossier = os.path.dirname(os.path.abspath(self.chemin))
            fd, temporaire = tempfile.mkstemp(dir=dossier, prefix=".etat-", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(json.dumps(contenu, ensure_ascii=False))
                os.replace(temporaire, self.chemin)
            except BaseException:
                try:
                    os.unlink(temporaire)
                except OSError:
                    pass
                raise
            return version
