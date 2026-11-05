"""Tests de la version Pythonista (serveur interne), avec des Rappels et un agenda simulés."""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

ICI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ICI)

import appli_locale  # noqa: E402
import plateforme  # noqa: E402
from liens import soiree  # noqa: E402
from smartlife import SmartLife  # noqa: E402
from tuya_cloud import signer  # noqa: E402

PARIS = timezone(timedelta(hours=1))


def ev(titre, h1, h2, journee=False):
    jour = "2026-11-05"
    if journee:
        return {"titre": titre, "debut": jour, "fin": "2026-11-06", "journee": True}
    return {"titre": titre, "debut": f"{jour}T{h1}:00+01:00", "fin": f"{jour}T{h2}:00+01:00", "journee": False}


MIDI = datetime(2026, 11, 5, 12, 0, tzinfo=PARIS)


# ---------- Liens entre les fonctions ----------
def test_soiree_dehors():
    s = soiree([ev("Réunion", "09:00", "10:00"), ev("Dîner chez Paul", "20:00", "23:00")], MIDI)
    assert s == {"type": "dehors", "titre": "Dîner chez Paul", "heure": "20:00"}


def test_soiree_chargee():
    s = soiree([ev("Réunion parents", "18:30", "19:30"), ev("Anniversaire", "", "", journee=True)], MIDI)
    assert s == {"type": "charge", "titre": "Réunion parents", "heure": "18:30"}


def test_soiree_libre():
    assert soiree([ev("Dentiste", "14:00", "15:00"), ev("Footing", "22:00", "23:00")], MIDI) is None
    assert soiree([ev("Dîner", "18:00", "19:00")], datetime(2026, 11, 5, 20, 0, tzinfo=PARIS)) is None  # déjà passé
    assert soiree(None) is None


def test_signature_tuya_de_reference():
    # valeur calculée par tinytuya pour les mêmes paramètres
    e = signer("CLIENTID123", "SECRETabc", "GET", "/v1.0/token?grant_type=1", t=1700000000000)
    assert e["sign"] == "1E8827B5CBCBD42163E4FB7731811799BF938D3EAC13F77E464C93197A8FBA21"


# ---------- Rappels simulés ----------
def test_rappels_simules(tmp_path):
    r = plateforme.RappelsSimules(str(tmp_path / "r.json"))
    assert r.ajouter("Courses", "Lait (1 L)") and not r.ajouter("courses", "lait")  # pas de doublon
    assert r.ajouter("Maison", "Vitres")
    assert {(x["liste"], x["titre"]) for x in r.lire()} == {("Courses", "Lait (1 L)"), ("Maison", "Vitres")}
    assert r.terminer_titre("Courses", "Lait")
    assert [x["titre"] for x in r.lire()] == ["Vitres"]
    assert r.terminer(r.lire()[0]["id"]) and r.lire() == []


# ---------- Serveur interne ----------
class Client:
    def __init__(self, adresse):
        self.adresse = adresse

    def appel(self, methode, chemin, corps=None):
        donnees = json.dumps(corps).encode() if corps is not None else None
        req = urllib.request.Request(self.adresse + chemin.lstrip("/"), data=donnees, method=methode,
                                     headers={"Content-Type": "application/json"} if donnees else {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode(errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")

    def json(self, methode, chemin, corps=None):
        statut, texte = self.appel(methode, chemin, corps)
        return statut, json.loads(texte)


@pytest.fixture
def appli(tmp_path):
    rappels = plateforme.RappelsSimules(str(tmp_path / "rappels.json"))
    rappels.ajouter("Maison", "Payer la cantine")
    agenda = plateforme.AgendaSimule([ev("Dîner chez Paul", "20:00", "23:00")])
    coffre = plateforme.CoffreFichier(str(tmp_path / "coffre.json"))
    a = appli_locale.Appli(str(tmp_path / "donnees"), rappels, agenda, coffre)
    serveur, adresse = appli_locale.demarrer(a)
    yield a, Client(adresse), rappels, coffre
    serveur.shutdown()


def injecte(html, nom):
    debut = html.index(f"window.{nom} = ") + len(f"window.{nom} = ")
    fin = min(i for i in (html.find(";</script>", debut), html.find(";\n", debut)) if i > 0)
    return json.loads(html[debut:fin])


def test_pages(appli):
    _, c, _, _ = appli
    statut, html = c.appel("GET", "/")
    m = injecte(html, "MAISON")
    assert statut == 200 and m["mode"] == "appareil" and m["cocher"] and m["fuseau"] is None
    assert c.appel("GET", "/garde-manger")[0] == 200  # redirigé vers /garde-manger/
    gm = injecte(c.appel("GET", "/garde-manger/")[1], "GM")
    assert gm["rappels"] is True and gm["retour"] == "../" and gm["claude"] is False
    assert c.appel("GET", "/static/icone-192.png")[0] == 200
    assert c.appel("GET", "/garde-manger/static/apple-touch-icon.png")[0] == 200
    assert c.appel("GET", "/static/../appli_locale.py")[0] == 404
    assert c.appel("GET", "/static/%2e%2e/appli_locale.py")[0] == 404


def test_tableau_et_cocher(appli):
    _, c, _, _ = appli
    _, t = c.json("GET", "/api/tableau")
    assert [r["titre"] for r in t["rappels"]["rappels"]] == ["Payer la cantine"]
    assert t["agenda"]["evenements"][0]["titre"] == "Dîner chez Paul"
    identifiant = t["rappels"]["rappels"][0]["id"]
    assert c.json("POST", "/api/rappels/cocher", {"id": identifiant}) == (200, {"ok": True})
    assert c.json("GET", "/api/tableau")[1]["rappels"]["rappels"] == []
    assert c.json("POST", "/api/rappels/cocher", {"id": "inconnu"})[1] == {"ok": False}


def test_courses_garde_manger_vers_rappels(appli):
    _, c, rappels, _ = appli
    statut, r = c.json("POST", "/garde-manger/api/courses/rappels", {"ajouter": [{"titre": "Lardons", "quantite": "50 g"}, {"titre": "Œufs"}]})
    assert statut == 200 and r == {"liste": "Courses", "ajoutes": 2, "termines": 0}
    assert {x["titre"] for x in rappels.lire() if x["liste"] == "Courses"} == {"Lardons (50 g)", "Œufs"}
    assert c.json("POST", "/garde-manger/api/courses/rappels", {"terminer": ["Lardons"]})[1]["termines"] == 1
    assert {x["titre"] for x in rappels.lire() if x["liste"] == "Courses"} == {"Œufs"}


def test_etat_garde_manger_et_tableau(appli):
    _, c, _, _ = appli
    etat = {"courses": [{"id": "lait", "label": "Lait"}], "pantry": [{"id": "courgette", "label": "Courgettes", "urgent": True}]}
    assert c.json("PUT", "/garde-manger/api/etat", {"etat": etat})[1]["version"] == 1
    assert c.json("GET", "/garde-manger/api/etat")[1]["etat"] == etat
    assert c.json("GET", "/api/tableau")[1]["garde_manger"] == {"courses": ["Lait"], "a_finir": ["Courgettes"], "placard": 1}
    assert c.appel("PUT", "/garde-manger/api/etat", {"etat": [1]})[0] == 400
    assert "soiree" in injecte(c.appel("GET", "/garde-manger/")[1], "GM")  # calculé depuis l'agenda du jour


def test_reglages_dans_le_trousseau(appli):
    a, c, _, coffre = appli
    statut, r = c.json("POST", "/api/reglages", {"smartlife_cle": "ID", "smartlife_secret": "SECRET", "smartlife_alarme": "al1",
                                                  "smartlife_camera": "cam1", "liste_courses": "Épicerie"})
    assert statut == 200 and r["smartlife_relie"] and r["liste_courses"] == "Épicerie"
    assert "SECRET" not in json.dumps(r) and "SECRET" not in c.appel("GET", "/")[1]  # le secret ne revient jamais à la page
    assert coffre.lire()["smartlife_secret"] == "SECRET"
    c.json("POST", "/api/reglages", {"smartlife_secret": "", "liste_courses": "Épicerie"})
    assert coffre.lire()["smartlife_secret"] == "SECRET"  # vide = conservé
    m = injecte(c.appel("GET", "/")[1], "MAISON")
    assert m["alarme"] and m["camera"]
    # alarme et caméra avec un faux Tuya
    sys.path.insert(0, os.path.join(ICI, "tests"))
    from test_maison import FauxTuya
    a._smartlife = SmartLife("eu", "ID", "SECRET", "al1", "cam1", fabrique=FauxTuya)
    assert c.json("GET", "/api/tableau")[1]["alarme"]["libelle"] == "Activée (absence)"
    assert c.json("POST", "/api/camera/direct") == (200, {"url": "https://flux.example/live.m3u8"})


def test_camera_non_configuree(appli):
    _, c, _, _ = appli
    assert c.appel("POST", "/api/camera/direct", {})[0] == 404
    assert c.appel("POST", "/garde-manger/api/claude/plat", {"nom": "x"})[0] == 503
