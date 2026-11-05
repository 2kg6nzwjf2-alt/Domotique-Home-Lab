"""Maison sans serveur : l'appli tourne sur l'iPhone ou l'iPad, dans Pythonista.

Un petit serveur interne (bibliothèque standard, adresse 127.0.0.1 seulement) sert
les pages au navigateur intégré de Pythonista, le temps que l'appli est ouverte.
Les données (placard, courses) sont rangées dans iCloud Drive, donc partagées
entre l'iPhone et l'iPad ; les clés Smart Life restent dans le trousseau.
"""

import json
import mimetypes
import os
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ICI = os.path.dirname(os.path.abspath(__file__))
DOSSIER_GM = os.path.join(os.path.dirname(ICI), "garde-manger")
for chemin in (ICI, DOSSIER_GM):
    if chemin not in sys.path:
        sys.path.insert(0, chemin)

import donnees as donnees_gm  # noqa: E402  (garde-manger/donnees.py)
from liens import soiree  # noqa: E402
from smartlife import ErreurSmartLife, SmartLife  # noqa: E402
from stockage import EtatTropGros, Stockage  # noqa: E402  (garde-manger/stockage.py)

MARQUEUR_MAISON = "/*__MAISON__*/null"
MARQUEUR_GM = "/*__GARDE_MANGER__*/null"
REGLAGES_PUBLICS = ("smartlife_region", "smartlife_alarme", "smartlife_camera", "liste_courses")


def _json_page(valeur):
    return json.dumps(valeur, ensure_ascii=False).replace("</", "<\\/")


class Appli:
    """Toute la logique de l'appli, indépendante du serveur HTTP (facile à tester)."""

    def __init__(self, dossier_donnees, rappels, agenda_appareil, coffre):
        self.rappels, self.agenda_appareil, self.coffre = rappels, agenda_appareil, coffre
        self.etat_gm = Stockage(os.path.join(dossier_donnees, "garde-manger", "etat.json"))
        with open(os.path.join(ICI, "templates", "tableau.html"), encoding="utf-8") as f:
            self.page_maison = f.read()
        with open(os.path.join(DOSSIER_GM, "templates", "index.html"), encoding="utf-8") as f:
            self.page_gm = f.read()
        self._smartlife, self._agenda_ical = None, None
        self._charger_reglages()

    # ---------- Réglages ----------
    def _charger_reglages(self):
        r = self.coffre.lire()
        self.reglages = r
        self._smartlife = None
        if r.get("smartlife_cle") and r.get("smartlife_secret"):
            self._smartlife = SmartLife(r.get("smartlife_region") or "eu", r["smartlife_cle"], r["smartlife_secret"],
                                        r.get("smartlife_alarme"), r.get("smartlife_camera"))
        self._agenda_ical = None
        if r.get("agenda_ical"):
            from agenda import Agenda  # bibliothèques installées par l'installeur ; seulement si une adresse iCal est donnée
            self._agenda_ical = Agenda.depuis_texte(r["agenda_ical"], r.get("fuseau") or "Europe/Paris")

    def reglages_publics(self):
        r = self.reglages
        publics = {k: r.get(k, "") for k in REGLAGES_PUBLICS}
        publics["liste_courses"] = publics["liste_courses"] or "Courses"
        publics["smartlife_relie"] = bool(r.get("smartlife_cle") and r.get("smartlife_secret"))
        publics["agenda_ical"] = bool(r.get("agenda_ical"))
        return publics

    def enregistrer_reglages(self, nouveaux):
        r = dict(self.reglages)
        for cle in REGLAGES_PUBLICS:
            if cle in nouveaux:
                r[cle] = str(nouveaux[cle] or "").strip()[:200]
        for cle in ("smartlife_cle", "smartlife_secret", "agenda_ical"):
            valeur = str(nouveaux.get(cle) or "").strip()
            if valeur:  # vide = on garde la valeur enregistrée
                r[cle] = valeur[:2000]
            if nouveaux.get("effacer_" + cle):
                r.pop(cle, None)
        self.coffre.ecrire(r)
        self._charger_reglages()
        return self.reglages_publics()

    # ---------- Données ----------
    def agenda(self):
        source = self._agenda_ical or self.agenda_appareil
        if source is None:
            return None
        try:
            return source.du_jour()
        except Exception as e:
            return {"evenements": [], "erreurs": [f"Agenda illisible ({type(e).__name__})"]}

    def liste_courses(self):
        return self.reglages.get("liste_courses") or "Courses"

    def tableau(self):
        resultat = {}
        try:
            resultat["rappels"] = {"recu": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rappels": self.rappels.lire()}
        except Exception as e:
            resultat["rappels"] = {"recu": None, "rappels": [], "erreur": f"Rappels illisibles ({type(e).__name__}). Autorisez Pythonista : Réglages > Pythonista > Rappels."}
        agenda = self.agenda()
        if agenda is not None:
            resultat["agenda"] = agenda
        if self._smartlife and self._smartlife.alarme_id:
            try:
                resultat["alarme"] = self._smartlife.etat_alarme()
            except ErreurSmartLife as e:
                resultat["alarme"] = {"erreur": e.message}
            except Exception as e:
                resultat["alarme"] = {"erreur": f"Smart Life ne répond pas ({type(e).__name__})"}
        _, etat = self.etat_gm.lire()
        courses = etat.get("courses") if isinstance(etat.get("courses"), list) else []
        placard = etat.get("pantry") if isinstance(etat.get("pantry"), list) else []
        resultat["garde_manger"] = {
            "courses": [str(c.get("label", ""))[:60] for c in courses if isinstance(c, dict)][:50],
            "a_finir": [str(p.get("label", ""))[:60] for p in placard if isinstance(p, dict) and p.get("urgent")][:20],
            "placard": len(placard),
        }
        return resultat

    def soiree(self):
        agenda = self.agenda()
        return soiree(agenda["evenements"]) if agenda else None

    def courses_vers_rappels(self, corps):
        liste, ajoutes, termines = self.liste_courses(), 0, 0
        for element in (corps.get("ajouter") or [])[:50]:
            if isinstance(element, dict) and str(element.get("titre") or "").strip():
                titre = str(element["titre"]).strip()[:120]
                quantite = str(element.get("quantite") or "").strip()[:30]
                ajoutes += bool(self.rappels.ajouter(liste, f"{titre} ({quantite})" if quantite else titre))
        for titre in (corps.get("terminer") or [])[:50]:
            termines += bool(self.rappels.terminer_titre(liste, str(titre)))
        return {"liste": liste, "ajoutes": ajoutes, "termines": termines}

    def camera(self):
        if not (self._smartlife and self._smartlife.camera_id):
            raise ErreurSmartLife("aucune caméra configurée", "non_configure")
        return self._smartlife.flux_camera()

    # ---------- Pages ----------
    def page_tableau(self):
        r = self.reglages_publics()
        injecte = {
            "mode": "appareil",
            "fuseau": None,  # heure de l'appareil
            "agenda": True,
            "alarme": bool(self._smartlife and self._smartlife.alarme_id),
            "camera": bool(self._smartlife and self._smartlife.camera_id),
            "cocher": True,
            "reglages": r,
        }
        return self.page_maison.replace(MARQUEUR_MAISON, _json_page(injecte))

    def page_garde_manger(self):
        version, etat = self.etat_gm.lire()
        injecte = {"donnees": donnees_gm.pour_interface(), "etat": etat, "version": version, "claude": False,
                   "retour": "../", "rappels": True, "soiree": self.soiree()}
        return self.page_gm.replace(MARQUEUR_GM, _json_page(injecte))


class Gestionnaire(BaseHTTPRequestHandler):
    appli = None  # remplacé par demarrer()

    def log_message(self, *args):  # pas de journal dans la console de Pythonista
        pass

    def _envoyer(self, statut, corps, type_contenu="application/json; charset=utf-8", entetes=None):
        if isinstance(corps, (dict, list)):
            corps = json.dumps(corps, ensure_ascii=False)
        if isinstance(corps, str):
            corps = corps.encode("utf-8")
        self.send_response(statut)
        self.send_header("Content-Type", type_contenu)
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (entetes or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corps)

    def _corps(self):
        taille = int(self.headers.get("Content-Length") or 0)
        if taille > 2_000_000:
            raise ValueError("trop gros")
        brut = self.rfile.read(taille) if taille else b""
        valeur = json.loads(brut or b"{}")
        if not isinstance(valeur, dict):
            raise ValueError("objet JSON attendu")
        return valeur

    def _fichier(self, dossier, relatif):
        chemin = os.path.normpath(os.path.join(dossier, relatif))
        if not chemin.startswith(os.path.normpath(dossier) + os.sep) or not os.path.isfile(chemin):
            return self._envoyer(404, {"code": "introuvable"})
        type_contenu = "application/manifest+json" if chemin.endswith(".webmanifest") else (mimetypes.guess_type(chemin)[0] or "application/octet-stream")
        with open(chemin, "rb") as f:
            return self._envoyer(200, f.read(), type_contenu)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        a, chemin = self.appli, urlsplit(self.path).path
        if chemin == "/":
            return self._envoyer(200, a.page_tableau(), "text/html; charset=utf-8")
        if chemin == "/api/tableau":
            return self._envoyer(200, a.tableau())
        if chemin == "/api/reglages":
            return self._envoyer(200, a.reglages_publics())
        if chemin == "/manifest.webmanifest":
            return self._fichier(os.path.join(ICI, "static"), "manifest.webmanifest")
        if chemin.startswith("/static/"):
            return self._fichier(os.path.join(ICI, "static"), chemin[len("/static/"):])
        if chemin == "/garde-manger":
            return self._envoyer(301, b"", "text/plain", {"Location": "/garde-manger/"})
        if chemin == "/garde-manger/":
            return self._envoyer(200, a.page_garde_manger(), "text/html; charset=utf-8")
        if chemin == "/garde-manger/api/etat":
            version, etat = a.etat_gm.lire()
            return self._envoyer(200, {"version": version, "etat": etat})
        if chemin == "/garde-manger/api/etat/version":
            return self._envoyer(200, {"version": a.etat_gm.lire()[0]})
        if chemin == "/garde-manger/manifest.webmanifest":
            return self._fichier(os.path.join(DOSSIER_GM, "static"), "manifest.webmanifest")
        if chemin.startswith("/garde-manger/static/"):
            return self._fichier(os.path.join(DOSSIER_GM, "static"), chemin[len("/garde-manger/static/"):])
        return self._envoyer(404, {"code": "introuvable"})

    def do_PUT(self):
        if urlsplit(self.path).path != "/garde-manger/api/etat":
            return self._envoyer(404, {"code": "introuvable"})
        try:
            corps = self._corps()
            if not isinstance(corps.get("etat"), dict):
                raise ValueError("état manquant")
            return self._envoyer(200, {"version": self.appli.etat_gm.ecrire(corps["etat"])})
        except EtatTropGros:
            return self._envoyer(413, {"code": "bad_request", "message": "état trop volumineux"})
        except ValueError as e:
            return self._envoyer(400, {"code": "bad_request", "message": str(e)})

    def do_POST(self):
        a, chemin = self.appli, urlsplit(self.path).path
        try:
            corps = self._corps()
        except ValueError as e:
            return self._envoyer(400, {"code": "bad_request", "message": str(e)})
        try:
            if chemin == "/api/rappels/cocher":
                return self._envoyer(200, {"ok": bool(a.rappels.terminer(str(corps.get("id") or "")))})
            if chemin == "/api/reglages":
                return self._envoyer(200, a.enregistrer_reglages(corps))
            if chemin == "/api/camera/direct":
                try:
                    return self._envoyer(200, {"url": a.camera()})
                except ErreurSmartLife as e:
                    return self._envoyer(404 if e.code == "non_configure" else 502, {"code": e.code, "message": e.message})
            if chemin == "/garde-manger/api/courses/rappels":
                return self._envoyer(200, a.courses_vers_rappels(corps))
            if chemin.startswith("/garde-manger/api/claude/"):
                return self._envoyer(503, {"code": "indisponible", "message": "Claude n'est pas disponible dans cette version"})
        except Exception as e:  # une erreur d'iOS ne doit pas arrêter l'appli
            return self._envoyer(500, {"code": "erreur", "message": f"{type(e).__name__} : {e}"[:300]})
        return self._envoyer(404, {"code": "introuvable"})


def demarrer(appli, port=0):
    """Lance le serveur interne dans un fil d'exécution ; renvoie (serveur, adresse)."""
    gestionnaire = type("GestionnaireMaison", (Gestionnaire,), {"appli": appli})
    serveur = ThreadingHTTPServer(("127.0.0.1", port), gestionnaire)
    serveur.daemon_threads = True
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    return serveur, f"http://127.0.0.1:{serveur.server_address[1]}/"
