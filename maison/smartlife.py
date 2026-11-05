"""Alarme et caméra Smart Life, par l'API cloud de Tuya (la plateforme derrière Smart Life).

Lecture seule : l'appli affiche l'état de l'alarme et la vidéo en direct,
elle n'arme ni ne désarme jamais l'alarme.
"""

import threading
import time

DUREE_CACHE_ALARME = 15  # secondes

# Codes usuels des centrales d'alarme Tuya (catégorie « mal »)
MODES = {
    "disarmed": ("Désactivée", "off"),
    "arm": ("Activée (absence)", "on"),
    "home": ("Activée (présence)", "on"),
    "sos": ("SOS", "alerte"),
}
CODES_MODE = ("master_mode", "alarm_mode", "mode")
CODES_ETAT = ("master_state", "alarm_state")


class ErreurSmartLife(Exception):
    def __init__(self, message, code="smartlife"):
        super().__init__(message)
        self.message = message
        self.code = code


def _verifier(reponse, quoi):
    """tinytuya renvoie un dictionnaire d'erreur au lieu de lever une exception."""
    if not isinstance(reponse, dict):
        raise ErreurSmartLife(f"{quoi} : réponse vide de Tuya")
    if reponse.get("success") is True:
        return reponse.get("result")
    message = reponse.get("msg") or reponse.get("Error") or reponse.get("Payload") or "erreur inconnue"
    raise ErreurSmartLife(f"{quoi} : {message}", str(reponse.get("code") or reponse.get("Err") or "smartlife"))


def lire_alarme(statuts, en_ligne=None):
    """Transforme la liste [{code, value}] de Tuya en un état lisible."""
    valeurs = {s.get("code"): s.get("value") for s in statuts or [] if isinstance(s, dict)}
    mode = next((str(valeurs[c]) for c in CODES_MODE if c in valeurs), None)
    etat = next((str(valeurs[c]) for c in CODES_ETAT if c in valeurs), None)
    libelle, niveau = MODES.get(mode, (mode or "Inconnu", "inconnu"))
    if etat == "alarm":
        libelle, niveau = "Alarme déclenchée", "alerte"
    return {"mode": mode, "libelle": libelle, "niveau": niveau, "en_ligne": en_ligne, "valeurs": valeurs}


class SmartLife:
    def __init__(self, region, cle, secret, alarme_id=None, camera_id=None, fabrique=None):
        self.region, self.cle, self.secret = region, cle, secret
        self.alarme_id, self.camera_id = alarme_id or None, camera_id or None
        self._fabrique = fabrique
        self._cloud = None
        self._cache = None
        self._verrou = threading.Lock()

    @classmethod
    def depuis_environnement(cls, env):
        cle, secret = env.get("SMARTLIFE_CLE"), env.get("SMARTLIFE_SECRET")
        if not cle or not secret:
            return None
        return cls(env.get("SMARTLIFE_REGION", "eu"), cle, secret,
                   env.get("SMARTLIFE_ALARME_ID"), env.get("SMARTLIFE_CAMERA_ID"))

    def _client(self):
        if self._cloud is None:
            if self._fabrique:
                self._cloud = self._fabrique()
            else:
                import tinytuya
                try:
                    self._cloud = tinytuya.Cloud(apiRegion=self.region, apiKey=self.cle, apiSecret=self.secret)
                except Exception as e:
                    raise ErreurSmartLife(f"Connexion à Tuya : Smart Life injoignable ({type(e).__name__})", "reseau") from e
            if getattr(self._cloud, "error", None):
                erreur, self._cloud = self._cloud.error, None
                _verifier(erreur if isinstance(erreur, dict) else {"msg": str(erreur)}, "Connexion à Tuya")
        return self._cloud

    def _appel(self, url, quoi, **kw):
        """Appel à Tuya ; une coupure réseau devient une ErreurSmartLife et la connexion sera refaite."""
        try:
            return _verifier(self._client().cloudrequest(url, **kw), quoi)
        except ErreurSmartLife:
            raise
        except Exception as e:  # requests, json… : tinytuya ne filtre pas les erreurs réseau
            self._cloud = None
            raise ErreurSmartLife(f"{quoi} : Smart Life injoignable ({type(e).__name__})", "reseau") from e

    def etat_alarme(self):
        if not self.alarme_id:
            return None
        with self._verrou:
            if self._cache and time.monotonic() - self._cache[0] < DUREE_CACHE_ALARME:
                return self._cache[1]
            statuts = self._appel(f"/v1.0/devices/{self.alarme_id}/status", "État de l'alarme")
            try:
                infos = self._appel(f"/v1.0/devices/{self.alarme_id}", "Infos de l'alarme")
                en_ligne = bool(infos.get("online")) if isinstance(infos, dict) else None
            except ErreurSmartLife:
                en_ligne = None
            etat = lire_alarme(statuts, en_ligne)
            etat["lu"] = int(time.time())
            self._cache = (time.monotonic(), etat)
            return etat

    def flux_camera(self):
        """Adresse HLS temporaire du direct (Safari la lit sans extension)."""
        if not self.camera_id:
            raise ErreurSmartLife("aucune caméra configurée", "non_configure")
        resultat = self._appel(f"/v1.0/devices/{self.camera_id}/stream/actions/allocate", "Vidéo de la caméra",
                               action="POST", post={"type": "hls"})
        url = resultat.get("url") if isinstance(resultat, dict) else None
        if not url:
            raise ErreurSmartLife("Tuya n'a pas fourni d'adresse vidéo")
        return url
