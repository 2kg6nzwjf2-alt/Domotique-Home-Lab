"""Codes-barres : vérification du numéro (EAN-13, EAN-8, UPC-A) et fiche produit Open Food Facts.

Open Food Facts (https://world.openfoodfacts.org) est une base de données
collaborative, gratuite et sans compte. Seul le numéro du code-barres lui est envoyé.
"""

import re
import threading
import time

import requests

ADRESSE = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
CHAMPS = "product_name,product_name_fr,generic_name_fr,brands,quantity,categories"
AGENT = "Garde-manger/1.0 (projet personnel ; github.com/2kg6nzwjf2-alt/Domotique-Home-Lab)"
DUREE_CACHE = 7 * 24 * 3600


class ErreurCode(Exception):
    def __init__(self, message, code="erreur"):
        super().__init__(message)
        self.message, self.code = message, code


def code_valide(texte):
    """Renvoie le code nettoyé (EAN-13 ou EAN-8) si sa clé de contrôle est juste, sinon None."""
    chiffres = re.sub(r"\D", "", str(texte or ""))
    if len(chiffres) == 12:  # UPC-A : même code qu'un EAN-13 commençant par 0
        chiffres = "0" + chiffres
    if len(chiffres) not in (8, 13):
        return None
    corps, cle = chiffres[:-1], int(chiffres[-1])
    # pondération 3 et 1 en partant du chiffre le plus proche de la clé
    total = sum(int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(reversed(corps)))
    return chiffres if (10 - total % 10) % 10 == cle else None


def fiche(produit):
    """Réduit la fiche Open Food Facts à ce dont l'appli a besoin."""
    nom = (produit.get("product_name_fr") or produit.get("product_name") or "").strip()
    categories = [c.strip() for c in str(produit.get("categories") or "").split(",") if c.strip()]
    return {
        "nom": nom[:120],
        "marque": str(produit.get("brands") or "").split(",")[0].strip()[:60],
        "quantite": str(produit.get("quantity") or "").strip()[:40],
        "generique": str(produit.get("generic_name_fr") or "").strip()[:120],
        "categories": [c[:60] for c in categories][-8:],
    }


class OpenFoodFacts:
    def __init__(self, session=None):
        self.session = session or requests.Session()
        self._cache = {}
        self._verrou = threading.Lock()

    def chercher(self, texte):
        code = code_valide(texte)
        if not code:
            raise ErreurCode("Ce code-barres n'est pas valide : vérifiez les chiffres.", "invalide")
        with self._verrou:
            en_cache = self._cache.get(code)
            if en_cache and time.monotonic() - en_cache[0] < DUREE_CACHE:
                return en_cache[1]
        try:
            r = self.session.get(ADRESSE.format(code=code), params={"fields": CHAMPS},
                                 headers={"User-Agent": AGENT}, timeout=12)
            donnees = r.json() if r.status_code in (200, 404) else None
        except (requests.RequestException, ValueError) as e:
            raise ErreurCode(f"Open Food Facts injoignable ({type(e).__name__}). Vérifiez la connexion.", "reseau") from e
        if donnees is None:
            raise ErreurCode(f"Open Food Facts ne répond pas (erreur {r.status_code}).", "reseau")
        produit = donnees.get("product") if donnees.get("status") == 1 else None
        resultat = {"code": code, "trouve": bool(produit), **(fiche(produit) if produit else {})}
        if resultat["trouve"] and not resultat["nom"]:
            resultat["trouve"] = False  # fiche sans nom : inutilisable
        with self._verrou:
            self._cache[code] = (time.monotonic(), resultat)
        return resultat
