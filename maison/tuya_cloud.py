"""Client minimal de l'API cloud Tuya (Smart Life), en Python pur.

Sans dépendance compilée : il fonctionne sur un serveur comme dans Pythonista.
Signature « HMAC-SHA256, nouvel algorithme » documentée par Tuya.
"""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import requests

HOTES = {
    "eu": "https://openapi.tuyaeu.com",        # Europe centrale
    "weu": "https://openapi-weaz.tuyaeu.com",  # Europe de l'Ouest
    "us": "https://openapi.tuyaus.com",
    "cn": "https://openapi.tuyacn.com",
    "in": "https://openapi.tuyain.com",
}


def signer(client_id, secret, methode, chemin, corps="", jeton="", t=None, nonce="", entetes_signes=None):
    """Renvoie les en-têtes signés d'une requête Tuya.

    `entetes_signes` : en-têtes inclus dans la signature (Signature-Headers), comme le fait tinytuya.
    """
    t = str(t or int(time.time() * 1000))
    entetes = dict(entetes_signes or {})
    lignes = ""
    if entetes:
        entetes["Signature-Headers"] = ":".join(entetes)
        lignes = "".join(f"{k}:{v}\n" for k, v in entetes.items() if k != "Signature-Headers")
    a_signer = f"{methode.upper()}\n{hashlib.sha256(corps.encode('utf-8')).hexdigest()}\n{lignes}\n{chemin}"
    message = client_id + jeton + t + nonce + a_signer
    signature = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest().upper()
    entetes.update({"client_id": client_id, "sign": signature, "t": t, "sign_method": "HMAC-SHA256"})
    if nonce:
        entetes["nonce"] = nonce
    if jeton:
        entetes["access_token"] = jeton
    return entetes


class TuyaCloud:
    def __init__(self, region, client_id, secret, session=None, delai=15):
        self.hote = HOTES.get(region, region if str(region).startswith("http") else HOTES["eu"])
        self.client_id, self.secret = client_id, secret
        self.session = session or requests.Session()
        self.delai = delai
        self._jeton, self._expire = "", 0.0

    def _envoyer(self, methode, chemin, corps=None, jeton=""):
        texte = json.dumps(corps) if corps is not None else ""
        signes = {"Content-type": "application/json"} if methode == "POST" else None
        entetes = signer(self.client_id, self.secret, methode, chemin, texte, jeton, entetes_signes=signes)
        r = self.session.request(methode, self.hote + chemin, data=texte or None, headers=entetes, timeout=self.delai)
        try:
            return r.json()
        except ValueError:
            return {"success": False, "msg": f"réponse illisible (HTTP {r.status_code})"}

    def _jeton_valide(self):
        if self._jeton and time.time() < self._expire - 60:
            return self._jeton
        reponse = self._envoyer("GET", "/v1.0/token?grant_type=1")
        if not reponse.get("success"):
            return None, reponse
        resultat = reponse.get("result") or {}
        self._jeton = resultat.get("access_token", "")
        self._expire = time.time() + int(resultat.get("expire_time", 3600))
        return self._jeton

    def cloudrequest(self, chemin, action=None, post=None, query=None):
        """Même usage que tinytuya.Cloud.cloudrequest : renvoie le dictionnaire de Tuya."""
        jeton = self._jeton_valide()
        if isinstance(jeton, tuple):
            return jeton[1]
        if query:
            chemin += ("&" if "?" in chemin else "?") + urlencode(sorted(query.items()))
        methode = action or ("POST" if post is not None else "GET")
        reponse = self._envoyer(methode, chemin, post, jeton)
        if reponse.get("code") in (1010, 1011):  # jeton expiré ou invalide : une seule nouvelle tentative
            self._jeton = ""
            jeton = self._jeton_valide()
            if isinstance(jeton, tuple):
                return jeton[1]
            reponse = self._envoyer(methode, chemin, post, jeton)
        return reponse
