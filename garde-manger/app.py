"""Garde-manger : serveur Python (Flask) de l'appli.

Lancement :   python app.py
Puis, sur l'iPhone ou l'iPad (même Wi-Fi) : ouvrez l'adresse affichée dans Safari,
et « Partager > Sur l'écran d'accueil » pour l'utiliser comme une appli.
"""

import hmac
import json
import os
import secrets
import socket
from datetime import timedelta

from flask import Flask, Response, jsonify, redirect, request, send_from_directory, session, url_for

import donnees
from service_claude import ErreurClaude, ServiceClaude
from stockage import EtatTropGros, Stockage

DOSSIER = os.path.dirname(os.path.abspath(__file__))
MARQUEUR = "/*__GARDE_MANGER__*/null"


def _cle_secrete(dossier_donnees):
    """Clé qui signe le cookie de connexion : celle de l'environnement, sinon une clé gardée sur disque."""
    if os.environ.get("GM_CLE_SECRETE"):
        return os.environ["GM_CLE_SECRETE"]
    chemin = os.path.join(dossier_donnees, ".cle_secrete")
    try:
        with open(chemin, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        cle = secrets.token_hex(32)
        os.makedirs(dossier_donnees, exist_ok=True)
        with open(chemin, "w", encoding="utf-8") as f:
            f.write(cle)
        return cle


def _texte(valeur, longueur=120):
    return str(valeur or "").strip()[:longueur]


def _personnes(valeur):
    try:
        return min(12, max(1, int(valeur)))
    except (TypeError, ValueError):
        return 2


def _soiree(fonction):
    if fonction is None:
        return None
    try:
        return fonction()
    except Exception:  # l'agenda ne doit jamais empêcher d'ouvrir Garde-manger
        return None


def _liste_textes(valeur, nombre=40, longueur=80):
    if not isinstance(valeur, list):
        return []
    return [_texte(v, longueur) for v in valeur[:nombre] if _texte(v, longueur)]


def create_app(dossier_donnees=None, mot_de_passe=None, claude="environnement", cle_secrete=None, retour=None, soiree=None):
    """`cle_secrete`, `retour` et `soiree` servent quand Garde-manger est une sous-appli du tableau de bord Maison.

    `soiree` : fonction sans argument qui renvoie le repas dehors ou la soirée chargée du jour (ou None).
    """
    dossier_donnees = dossier_donnees or os.environ.get("GM_DOSSIER_DONNEES") or os.path.join(DOSSIER, "donnees_utilisateur")
    mot_de_passe = os.environ.get("GM_MOT_DE_PASSE") if mot_de_passe is None else mot_de_passe
    if claude == "environnement":
        claude = ServiceClaude.depuis_environnement()

    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.update(
        SECRET_KEY=cle_secrete or _cle_secrete(dossier_donnees),
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
        PERMANENT_SESSION_LIFETIME=timedelta(days=365),
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_HTTPONLY=True,
    )
    stockage = Stockage(os.path.join(dossier_donnees, "etat.json"))
    with open(os.path.join(DOSSIER, "templates", "index.html"), encoding="utf-8") as f:
        page = f.read()
    if MARQUEUR not in page:
        raise RuntimeError("templates/index.html ne contient pas le marqueur des données")

    # ---------- Connexion (seulement si un mot de passe est défini) ----------
    LIBRES = {"connexion", "static", "manifeste"}

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
            saisi = request.form.get("mot_de_passe", "")
            if mot_de_passe and hmac.compare_digest(saisi.encode(), mot_de_passe.encode()):
                session.permanent = True
                session["connecte"] = True
                return redirect(url_for("accueil"))
            erreur = "<p class=\"err\">Mot de passe incorrect.</p>"
        return Response(PAGE_CONNEXION.replace("{erreur}", erreur), mimetype="text/html")

    # ---------- Pages ----------
    @app.get("/")
    def accueil():
        version, etat = stockage.lire()
        injecte = {
            "donnees": donnees.pour_interface(),
            "etat": etat,
            "version": version,
            "claude": claude is not None,
            "retour": retour,
            "soiree": _soiree(soiree),
        }
        # « </ » échappé pour qu'aucun texte ne puisse fermer la balise <script>
        json_injecte = json.dumps(injecte, ensure_ascii=False).replace("</", "<\\/")
        reponse = Response(page.replace(MARQUEUR, json_injecte), mimetype="text/html")
        reponse.headers["Cache-Control"] = "no-store"
        return reponse

    @app.get("/manifest.webmanifest")
    def manifeste():
        return send_from_directory(app.static_folder, "manifest.webmanifest", mimetype="application/manifest+json")

    # ---------- État partagé entre les appareils ----------
    @app.get("/api/etat")
    def lire_etat():
        version, etat = stockage.lire()
        return jsonify(version=version, etat=etat)

    @app.get("/api/etat/version")
    def lire_version():
        version, _ = stockage.lire()
        return jsonify(version=version)

    @app.put("/api/etat")
    def ecrire_etat():
        corps = request.get_json(silent=True)
        if not isinstance(corps, dict) or not isinstance(corps.get("etat"), dict):
            return jsonify(code="bad_request", message="état manquant"), 400
        try:
            version = stockage.ecrire(corps["etat"])
        except EtatTropGros:
            return jsonify(code="bad_request", message="état trop volumineux"), 413
        return jsonify(version=version)

    # ---------- Claude ----------
    def avec_claude(fonction):
        if claude is None:
            return jsonify(code="indisponible", message="aucune clé API Anthropic configurée"), 503
        try:
            return jsonify(fonction())
        except ErreurClaude as e:
            return jsonify(code=e.code, message=e.message), e.statut

    @app.post("/api/claude/plat")
    def claude_plat():
        corps = request.get_json(silent=True) or {}
        nom = _texte(corps.get("nom"), 80)
        if not nom:
            return jsonify(code="bad_request", message="nom du plat manquant"), 400
        return avec_claude(lambda: {"recette": claude.recette(nom, _personnes(corps.get("personnes")), _liste_textes(corps.get("ustensiles")))})

    @app.post("/api/claude/idees")
    def claude_idees():
        corps = request.get_json(silent=True) or {}
        placard = []
        for item in (corps.get("placard") or [])[:150]:
            if isinstance(item, dict) and _texte(item.get("nom"), 60):
                placard.append({"nom": _texte(item.get("nom"), 60), "quantite": _texte(item.get("quantite"), 30), "a_finir": bool(item.get("a_finir"))})
        if not placard:
            return jsonify(code="bad_request", message="placard vide"), 400
        filtres = corps.get("filtres") if isinstance(corps.get("filtres"), dict) else {}
        filtres = {
            "vegetarien": bool(filtres.get("vegetarien")),
            "rapide": bool(filtres.get("rapide")),
            "facile": bool(filtres.get("facile")),
            "type": filtres.get("type") if filtres.get("type") in ("plat", "entree", "dessert") else "tout",
        }
        return avec_claude(lambda: {"recettes": claude.idees(
            placard, _personnes(corps.get("personnes")), _liste_textes(corps.get("ustensiles")), filtres, _liste_textes(corps.get("deja"), 20))})

    @app.post("/api/claude/photo")
    def claude_photo():
        fichier = request.files.get("image")
        if not fichier:
            return jsonify(code="bad_request", message="photo manquante"), 400
        image = fichier.read()
        if not image or len(image) > 5 * 1024 * 1024:
            return jsonify(code="image_rejected", message="photo vide ou trop lourde"), 400
        return avec_claude(lambda: {"produits": claude.produits_sur_photo(image, fichier.mimetype)})

    return app


PAGE_CONNEXION = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes"><title>Garde-manger</title>
<link rel="apple-touch-icon" href="/static/apple-touch-icon.png">
<style>
:root{--bg:#f3f5f9;--fg:#14213a;--line:#d8deea;--accent:#1c4da1;--err:#bf3f2b}
@media (prefers-color-scheme:dark){:root{--bg:#0d1422;--fg:#e6ebf5;--line:#2a3756;--accent:#86a8ee;--err:#f08c79}}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--fg);font:16px/1.5 -apple-system,system-ui,sans-serif;padding:16px}
form{display:flex;flex-direction:column;gap:12px;width:min(340px,100%)}
h1{margin:0 0 8px;font-size:26px}
input{font:inherit;padding:12px;border-radius:10px;border:1.5px solid var(--line);background:transparent;color:inherit}
button{font:inherit;font-weight:600;padding:12px;border:0;border-radius:10px;background:var(--accent);color:var(--bg)}
.err{color:var(--err);margin:0}
</style></head><body>
<form method="post"><h1>Garde-manger</h1>{erreur}
<label for="mdp">Mot de passe</label>
<input id="mdp" name="mot_de_passe" type="password" autocomplete="current-password" autofocus>
<button type="submit">Entrer</button></form></body></html>"""


def _adresse_locale():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 80))  # adresse de test, aucun paquet n'est envoyé
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


if __name__ == "__main__":
    hote = os.environ.get("GM_HOTE", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("GM_PORT", "5000")))
    application = create_app()
    print(f"Garde-manger est lancé. Sur l'iPhone ou l'iPad, ouvrez : http://{_adresse_locale()}:{port}")
    if not os.environ.get("GM_MOT_DE_PASSE"):
        print("Aucun mot de passe : toute personne sur votre réseau Wi-Fi peut ouvrir l'appli (voir README).")
    try:
        from waitress import serve
    except ImportError:
        application.run(host=hote, port=port)
    else:
        serve(application, host=hote, port=port)
