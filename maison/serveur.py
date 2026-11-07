"""Maison : tableau de bord de la maison (météo, agenda, tâches) et ses sous-applis.

Lancement :   python serveur.py
Garde-manger est servi à l'adresse /garde-manger/.
"""

import hmac
import json
import os
import secrets
import socket
import sys
import time
from datetime import timedelta

from flask import Flask, Response, jsonify, redirect, request, send_from_directory, session, url_for
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.middleware.proxy_fix import ProxyFix

DOSSIER = os.path.dirname(os.path.abspath(__file__))
DOSSIER_GM = os.path.join(os.path.dirname(DOSSIER), "garde-manger")
sys.path.insert(0, DOSSIER_GM)

import app as garde_manger  # noqa: E402  (garde-manger/app.py)
from stockage import Stockage  # noqa: E402  (garde-manger/stockage.py)

from agenda import Agenda  # noqa: E402
from liens import soiree  # noqa: E402
from rappels import Rappels, analyser_json, analyser_texte  # noqa: E402
from meteo import ErreurMeteo, Meteo  # noqa: E402

MARQUEUR = "/*__MAISON__*/null"
NOM_RACCOURCI = "Envoyer mes rappels"
ESSAIS_MAX, PAUSE_ESSAIS = 5, 60  # tentatives de mot de passe, puis attente en secondes


def _lire_ou_creer(chemin, longueur):
    try:
        with open(chemin, encoding="utf-8") as f:
            valeur = f.read().strip()
            if valeur:
                return valeur
    except OSError:
        pass
    valeur = secrets.token_urlsafe(longueur)
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(valeur)
    return valeur


class Redirection:
    """/garde-manger devient /garde-manger/ : l'appli utilise des adresses relatives."""

    def __init__(self, appli, prefixe):
        self.appli, self.prefixe = appli, prefixe

    def __call__(self, environ, start_response):
        if environ.get("PATH_INFO") == self.prefixe:
            cible = environ.get("SCRIPT_NAME", "") + self.prefixe + "/"
            start_response("308 Permanent Redirect", [("Location", cible), ("Content-Length", "0")])
            return [b""]
        return self.appli(environ, start_response)


def create_app(dossier_donnees=None, mot_de_passe=None, cle_raccourci=None, agenda="environnement",
               claude="environnement", fuseau=None, https=None, meteo="environnement"):
    env = os.environ
    dossier_donnees = dossier_donnees or env.get("MAISON_DONNEES") or os.path.join(DOSSIER, "donnees_utilisateur")
    os.makedirs(dossier_donnees, exist_ok=True)
    mot_de_passe = env.get("MAISON_MOT_DE_PASSE", "") if mot_de_passe is None else mot_de_passe
    fuseau = fuseau or env.get("MAISON_FUSEAU", "Europe/Paris")
    https = env.get("MAISON_HTTPS") == "1" if https is None else https
    if agenda == "environnement":
        agenda = Agenda.depuis_texte(env.get("MAISON_AGENDA_ICAL"), fuseau)
    if meteo == "environnement":
        meteo = Meteo.depuis_texte(env.get("MAISON_VILLE"))
    cle_secrete = env.get("MAISON_CLE_SECRETE") or _lire_ou_creer(os.path.join(dossier_donnees, ".cle_secrete"), 32)
    cle_raccourci = cle_raccourci or env.get("MAISON_CLE_RACCOURCI") or _lire_ou_creer(os.path.join(dossier_donnees, ".cle_raccourci"), 24)

    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.update(
        SECRET_KEY=cle_secrete,
        PERMANENT_SESSION_LIFETIME=timedelta(days=90),
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=https,
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )
    rappels = Rappels(os.path.join(dossier_donnees, "rappels.json"))
    dossier_gm = os.path.join(dossier_donnees, "garde-manger")
    etat_gm = Stockage(os.path.join(dossier_gm, "etat.json"))
    with open(os.path.join(DOSSIER, "templates", "tableau.html"), encoding="utf-8") as f:
        page = f.read()
    if MARQUEUR not in page:
        raise RuntimeError("templates/tableau.html ne contient pas le marqueur des données")
    echecs = {}

    # ---------- Connexion ----------
    LIBRES = {"connexion", "static", "manifeste", "recevoir_rappels"}

    @app.before_request
    def verifier_connexion():
        if not mot_de_passe or request.endpoint in LIBRES or session.get("connecte"):
            return None
        if request.path.startswith("/api/"):
            return jsonify(code="connexion", message="connexion requise"), 401
        return redirect(url_for("connexion"))

    @app.route("/connexion", methods=["GET", "POST"])
    def connexion():
        erreur = ""
        if request.method == "POST":
            ip = request.remote_addr or "?"
            nombre, depuis = echecs.get(ip, (0, 0))
            if nombre >= ESSAIS_MAX and time.monotonic() - depuis < PAUSE_ESSAIS:
                erreur = "Trop d'essais. Réessayez dans une minute."
            elif mot_de_passe and hmac.compare_digest(request.form.get("mot_de_passe", "").encode(), mot_de_passe.encode()):
                echecs.pop(ip, None)
                session.permanent = True
                session["connecte"] = True
                return redirect(url_for("tableau"))
            else:
                echecs[ip] = (nombre + 1 if nombre < ESSAIS_MAX else 1, time.monotonic())
                erreur = "Mot de passe incorrect."
        html = garde_manger.PAGE_CONNEXION.replace("Garde-manger</h1>", "Maison</h1>").replace("<title>Garde-manger", "<title>Maison")
        return Response(html.replace("{erreur}", f'<p class="err">{erreur}</p>' if erreur else ""), mimetype="text/html")

    @app.post("/deconnexion")
    def deconnexion():
        session.clear()
        return redirect(url_for("connexion"))

    # ---------- Pages ----------
    @app.get("/")
    def tableau():
        injecte = {
            "fuseau": fuseau,
            "agenda": agenda is not None,
            "raccourci": {"nom": NOM_RACCOURCI, "adresse": request.host_url.rstrip("/") + url_for("recevoir_rappels"), "cle": cle_raccourci},
            "motDePasse": bool(mot_de_passe),
            "mode": "serveur",
            "meteo": meteo is not None,
        }
        json_injecte = json.dumps(injecte, ensure_ascii=False).replace("</", "<\\/")
        reponse = Response(page.replace(MARQUEUR, json_injecte), mimetype="text/html")
        reponse.headers["Cache-Control"] = "no-store"
        return reponse

    @app.get("/manifest.webmanifest")
    def manifeste():
        return send_from_directory(app.static_folder, "manifest.webmanifest", mimetype="application/manifest+json")

    # ---------- Données du tableau de bord ----------
    @app.get("/api/tableau")
    def donnees_tableau():
        resultat = {"rappels": rappels.lire()}
        if meteo is not None:
            try:
                resultat["meteo"] = meteo.previsions()
            except ErreurMeteo as e:
                resultat["meteo"] = {"erreur": str(e)}
        if agenda is not None:
            try:
                resultat["agenda"] = agenda.du_jour()
            except Exception:  # un agenda abîmé ne doit pas casser tout le tableau
                app.logger.exception("agenda")
                resultat["agenda"] = {"evenements": [], "erreurs": ["Agenda illisible"]}
        _, etat = etat_gm.lire()
        courses = etat.get("courses") if isinstance(etat.get("courses"), list) else []
        placard = etat.get("pantry") if isinstance(etat.get("pantry"), list) else []
        resultat["garde_manger"] = {
            "courses": [str(c.get("label", ""))[:60] for c in courses if isinstance(c, dict)][:50],
            "a_finir": [str(p.get("label", ""))[:60] for p in placard if isinstance(p, dict) and p.get("urgent")][:20],
            "placard": len(placard),
        }
        return jsonify(resultat)

    @app.post("/api/rappels")
    def recevoir_rappels():
        cle = request.headers.get("X-Cle") or request.form.get("cle") or request.args.get("cle") or ""
        if not hmac.compare_digest(cle.encode(), cle_raccourci.encode()):
            return jsonify(code="cle", message="clé du Raccourci incorrecte"), 403
        try:
            if request.is_json:
                liste = analyser_json(request.get_json(silent=True))
            else:
                texte = request.form.get("texte")
                liste = analyser_texte(texte if texte is not None else request.get_data(as_text=True))
        except ValueError as e:
            return jsonify(code="bad_request", message=str(e)), 400
        contenu = rappels.enregistrer(liste)
        return jsonify(recus=len(liste), recu=contenu["recu"])

    # ---------- Sous-appli Garde-manger ----------
    sous_appli = garde_manger.create_app(dossier_donnees=dossier_gm, mot_de_passe=mot_de_passe, claude=claude,
                                         cle_secrete=cle_secrete, retour="../",
                                         soiree=(lambda: soiree(agenda.du_jour()["evenements"])) if agenda else None)
    sous_appli.config.update(SESSION_COOKIE_SECURE=https, PERMANENT_SESSION_LIFETIME=timedelta(days=90))

    @sous_appli.before_request
    def connexion_commune():
        # une seule connexion pour tout : la page de connexion est celle de Maison
        if mot_de_passe and not session.get("connecte") and not request.path.startswith("/static/") \
                and request.endpoint not in ("manifeste",):
            if request.path.startswith("/api/"):
                return jsonify(code="connexion", message="connexion requise"), 401
            return redirect(request.script_root.rsplit("/garde-manger", 1)[0] + "/connexion")
        return None

    sous_appli.before_request_funcs[None].insert(0, sous_appli.before_request_funcs[None].pop())

    app.wsgi_app = Redirection(DispatcherMiddleware(app.wsgi_app, {"/garde-manger": sous_appli}), "/garde-manger")
    if https:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    return app


def _adresse_locale():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 80))  # adresse de test, aucun paquet n'est envoyé
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


if __name__ == "__main__":
    if not os.environ.get("MAISON_MOT_DE_PASSE") and os.environ.get("MAISON_SANS_MOT_DE_PASSE") != "1":
        sys.exit("Définissez MAISON_MOT_DE_PASSE : le tableau de bord montre votre agenda et vos tâches.\n"
                 "(Pour un essai sur votre seul ordinateur : MAISON_SANS_MOT_DE_PASSE=1.)")
    port = int(os.environ.get("PORT", os.environ.get("MAISON_PORT", "8000")))
    application = create_app()
    print(f"Maison est lancé : http://{_adresse_locale()}:{port}")
    from waitress import serve
    serve(application, host=os.environ.get("MAISON_HOTE", "0.0.0.0"), port=port)
