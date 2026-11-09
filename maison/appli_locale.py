"""Maison sans serveur : l'appli tourne sur l'iPhone ou l'iPad, dans Pythonista.

Un petit serveur interne (bibliothèque standard, adresse 127.0.0.1 seulement) sert
les pages au navigateur intégré de Pythonista, le temps que l'appli est ouverte.
Les données (placard, courses) sont rangées dans iCloud Drive, donc partagées
entre l'iPhone et l'iPad ; les réglages restent dans le trousseau de l'appareil.
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
from plateforme import ListeIntrouvable  # noqa: E402
from plateforme import _cle_liste as plateforme_cle_liste  # noqa: E402
from menage import Menage  # noqa: E402
from meteo import ErreurMeteo, Meteo  # noqa: E402
from stockage import EnAttenteICloud, EtatTropGros, Stockage, VersionDepassee  # noqa: E402  (garde-manger/stockage.py)
from codes_barres import ErreurCode, OpenFoodFacts, code_valide  # noqa: E402  (garde-manger/codes_barres.py)

MARQUEUR_MAISON = "/*__MAISON__*/null"
MARQUEUR_GM = "/*__GARDE_MANGER__*/null"
REGLAGES_PUBLICS = ("liste_courses", "ville")
ANCIENS_REGLAGES = ("smartlife_cle", "smartlife_secret", "smartlife_region", "smartlife_alarme", "smartlife_camera")


def _json_page(valeur):
    return json.dumps(valeur, ensure_ascii=False).replace("</", "<\\/")


class Appli:
    """Toute la logique de l'appli, indépendante du serveur HTTP (facile à tester)."""

    def __init__(self, dossier_donnees, rappels, agenda_appareil, coffre, scanner=None, off=None,
                 icloud=None, appareil=None, partage=None):
        """`icloud` : objet avec `rafraichir(chemin)` (téléchargement depuis iCloud avant lecture).
        `partage` : "icloud" si les données sont dans iCloud Drive, "appareil" sinon (affiché dans les Réglages)."""
        self.rappels, self.agenda_appareil, self.coffre = rappels, agenda_appareil, coffre
        self.scanner, self.fiches = scanner, off or OpenFoodFacts()
        self.appareil, self.partage = appareil, partage
        rafraichir = icloud.rafraichir if icloud is not None else None
        self.etat_gm = Stockage(os.path.join(dossier_donnees, "garde-manger", "etat.json"), rafraichir, appareil)
        self.menage = Menage(os.path.join(dossier_donnees, "menage.json"), avant_lecture=rafraichir)
        with open(os.path.join(ICI, "templates", "tableau.html"), encoding="utf-8") as f:
            self.page_maison = f.read()
        with open(os.path.join(DOSSIER_GM, "templates", "index.html"), encoding="utf-8") as f:
            self.page_gm = f.read()
        self._agenda_ical = None
        self._charger_reglages()

    # ---------- Réglages ----------
    def _charger_reglages(self):
        r = self.coffre.lire()
        if any(cle in r for cle in ANCIENS_REGLAGES):  # Smart Life retiré : ses clés sont effacées du trousseau
            r = {k: v for k, v in r.items() if k not in ANCIENS_REGLAGES}
            self.coffre.ecrire(r)
        self.reglages = r
        self._meteo = Meteo.depuis_texte(r.get("ville"))
        self._agenda_ical = None
        if r.get("agenda_ical"):
            from agenda import Agenda  # bibliothèques installées par l'installeur ; seulement si une adresse iCal est donnée
            self._agenda_ical = Agenda.depuis_texte(r["agenda_ical"], r.get("fuseau") or "Europe/Paris")

    def reglages_publics(self):
        r = self.reglages
        publics = {k: r.get(k, "") for k in REGLAGES_PUBLICS}
        publics["liste_courses"] = publics["liste_courses"] or "Courses"
        publics["agenda_ical"] = bool(r.get("agenda_ical"))
        return publics

    def enregistrer_reglages(self, nouveaux):
        r = dict(self.reglages)
        for cle in REGLAGES_PUBLICS:
            if cle in nouveaux:
                r[cle] = str(nouveaux[cle] or "").strip()[:200]
        for cle in ("agenda_ical",):
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
            resultat["rappels"] = {"recu": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rappels": self.rappels.lire(),
                                   "avertissements": list(getattr(self.rappels, "erreurs", []))}
        except Exception as e:
            resultat["rappels"] = {"recu": None, "rappels": [], "erreur": f"Rappels illisibles ({type(e).__name__}). Autorisez Pythonista : Réglages > Pythonista > Rappels."}
        agenda = self.agenda()
        if agenda is not None:
            resultat["agenda"] = agenda
        if self._meteo is not None:
            try:
                resultat["meteo"] = self._meteo.previsions()
            except ErreurMeteo as e:
                resultat["meteo"] = {"erreur": str(e)}
        resultat["menage"] = self.menage.lire()
        infos = self.etat_gm.infos()
        resultat["synchro"] = {"placard": {k: infos[k] for k in ("appareil", "date", "en_attente")}}
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

    def listes_rappels(self):
        listes = self.rappels.listes()
        cle = plateforme_cle_liste(self.liste_courses())
        return {"listes": listes, "courses": self.liste_courses(), "trouvee": any(plateforme_cle_liste(l["nom"]) == cle for l in listes)}

    def courses_vers_rappels(self, corps):
        try:
            return self._courses_vers_rappels(corps)
        except ListeIntrouvable as e:
            return {"liste": self.liste_courses(), "ajoutes": 0, "termines": 0, "erreur": str(e)}

    def _courses_vers_rappels(self, corps):
        liste, ajoutes, termines = self.liste_courses(), 0, 0
        for element in (corps.get("ajouter") or [])[:50]:
            if isinstance(element, dict) and str(element.get("titre") or "").strip():
                titre = str(element["titre"]).strip()[:120]
                quantite = str(element.get("quantite") or "").strip()[:30]
                ajoutes += bool(self.rappels.ajouter(liste, f"{titre} ({quantite})" if quantite else titre))
        for titre in (corps.get("terminer") or [])[:50]:
            termines += bool(self.rappels.terminer_titre(liste, str(titre)))
        return {"liste": liste, "ajoutes": ajoutes, "termines": termines}

    # ---------- Pages ----------
    def page_tableau(self):
        r = self.reglages_publics()
        injecte = {
            "mode": "appareil",
            "fuseau": None,  # heure de l'appareil
            "agenda": True,
            "cocher": True,
            "meteo": self._meteo is not None,
            "reglages": r,
            "synchro": {"partage": self.partage, "appareil": self.appareil},
        }
        return self.page_maison.replace(MARQUEUR_MAISON, _json_page(injecte))

    def page_garde_manger(self):
        version, etat = self.etat_gm.lire()
        injecte = {"donnees": donnees_gm.pour_interface(), "etat": etat, "version": version, "claude": False,
                   "retour": "../", "rappels": True, "soiree": self.soiree(),
                   "codes": True, "scanner": self.scanner is not None}
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
        if chemin == "/api/rappels/listes":
            try:
                return self._envoyer(200, a.listes_rappels())
            except Exception as e:
                return self._envoyer(500, {"code": "erreur", "message": f"Rappels illisibles ({type(e).__name__})"})
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
        if chemin.startswith("/garde-manger/api/code/"):
            try:
                return self._envoyer(200, a.fiches.chercher(chemin.rsplit("/", 1)[1]))
            except ErreurCode as e:
                return self._envoyer(400 if e.code == "invalide" else 502, {"code": e.code, "message": e.message})
        if chemin == "/garde-manger/api/etat/version":
            return self._envoyer(200, {"version": a.etat_gm.lire()[0]})
        if chemin == "/garde-manger/manifest.webmanifest":
            return self._fichier(os.path.join(DOSSIER_GM, "static"), "manifest.webmanifest")
        if chemin.startswith("/garde-manger/static/"):
            return self._fichier(os.path.join(DOSSIER_GM, "static"), chemin[len("/garde-manger/static/"):])
        return self._envoyer(404, {"code": "introuvable"})

    def do_PUT(self):
        if urlsplit(self.path).path == "/api/menage/taches":
            try:
                return self._envoyer(200, {"taches": self.appli.menage.enregistrer_taches(self._corps().get("taches"))})
            except ValueError as e:
                return self._envoyer(400, {"code": "bad_request", "message": str(e)})
        if urlsplit(self.path).path != "/garde-manger/api/etat":
            return self._envoyer(404, {"code": "introuvable"})
        try:
            corps = self._corps()
            if not isinstance(corps.get("etat"), dict):
                raise ValueError("état manquant")
            base = corps.get("version")
            base = base if isinstance(base, int) and not isinstance(base, bool) else None
            return self._envoyer(200, {"version": self.appli.etat_gm.ecrire(corps["etat"], base)})
        except VersionDepassee as e:
            return self._envoyer(409, {"code": "conflit", "version": e.version})
        except EnAttenteICloud as e:
            return self._envoyer(503, {"code": "attente", "message": str(e)})
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
            if chemin == "/api/menage/cocher":
                try:
                    return self._envoyer(200, {"fait": a.menage.cocher(str(corps.get("tache") or ""), corps.get("date"), bool(corps.get("fait", True)))})
                except ValueError as e:
                    return self._envoyer(400, {"code": "bad_request", "message": str(e)})
            if chemin == "/garde-manger/api/scanner":
                if a.scanner is None:
                    return self._envoyer(404, {"code": "indisponible", "message": "Scan indisponible : tapez les chiffres du code-barres."})
                try:
                    texte = a.scanner.scanner()
                except ValueError as e:
                    return self._envoyer(200, {"erreur": str(e)})
                if texte is None:
                    return self._envoyer(200, {"annule": True})
                code = code_valide(texte)
                return self._envoyer(200, {"code": code} if code else {"erreur": f"Le code lu ({texte[:30]}) n'est pas un code-barres de produit."})
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
