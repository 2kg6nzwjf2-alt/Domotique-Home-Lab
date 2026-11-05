import json
import os
import sys
from datetime import date

import pytest

ICI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ICI)

from agenda import Agenda  # noqa: E402
from rappels import analyser_json, analyser_texte  # noqa: E402
from serveur import create_app  # noqa: E402
from smartlife import ErreurSmartLife, SmartLife, lire_alarme  # noqa: E402

CLE = "cle-du-raccourci"

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//FR
X-WR-CALNAME:Famille
BEGIN:VTIMEZONE
TZID:Europe/Paris
BEGIN:STANDARD
DTSTART:19701025T030000
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:19700329T020000
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
END:VTIMEZONE
BEGIN:VEVENT
UID:1
SUMMARY:Dentiste
LOCATION:Cabinet du centre
DTSTART;TZID=Europe/Paris:20261105T143000
DTEND;TZID=Europe/Paris:20261105T151500
END:VEVENT
BEGIN:VEVENT
UID:2
SUMMARY:Sport
DTSTART:20261002T170000Z
DTEND:20261002T180000Z
RRULE:FREQ=WEEKLY;BYDAY=TH
END:VEVENT
BEGIN:VEVENT
UID:3
SUMMARY:Anniversaire de Léa
DTSTART;VALUE=DATE:20261105
DTEND;VALUE=DATE:20261106
END:VEVENT
BEGIN:VEVENT
UID:4
SUMMARY:Annulé
STATUS:CANCELLED
DTSTART;TZID=Europe/Paris:20261105T090000
DTEND;TZID=Europe/Paris:20261105T100000
END:VEVENT
BEGIN:VEVENT
UID:5
SUMMARY:Demain
DTSTART;TZID=Europe/Paris:20261106T090000
DTEND;TZID=Europe/Paris:20261106T100000
END:VEVENT
END:VCALENDAR
""".replace("\n", "\r\n").encode("utf-8")


class FauxHTTP:
    def __init__(self, contenu=ICS, statut=200):
        self.contenu, self.statut, self.appels = contenu, statut, 0

    def get(self, url, timeout):
        import requests
        self.appels += 1
        r = requests.Response()
        r.status_code, r._content, r.url = self.statut, self.contenu, url
        return r


class FauxTuya:
    def __init__(self, statut=None, en_ligne=True, flux="https://flux.example/live.m3u8"):
        self.statut = statut or [{"code": "master_mode", "value": "arm"}, {"code": "master_state", "value": "normal"}]
        self.en_ligne, self.flux, self.appels = en_ligne, flux, []
        self.error = None

    def cloudrequest(self, url, action=None, post=None, query=None):
        self.appels.append((url, action, post))
        if url.endswith("/status"):
            return {"success": True, "result": self.statut}
        if url.endswith("/stream/actions/allocate"):
            if not self.flux:
                return {"success": False, "code": 1106, "msg": "permission deny"}
            return {"success": True, "result": {"url": self.flux}}
        return {"success": True, "result": {"online": self.en_ligne}}


def faux_smartlife(**kw):
    tuya = FauxTuya(**kw)
    return SmartLife("eu", "k", "s", "alarme1", "camera1", fabrique=lambda: tuya), tuya


@pytest.fixture
def appli(tmp_path):
    def fabrique(**kw):
        params = dict(dossier_donnees=str(tmp_path), mot_de_passe="", cle_raccourci=CLE, agenda=None, smartlife=None, claude=None)
        params.update(kw)
        return create_app(**params).test_client()
    return fabrique


def gm_injecte(html):
    debut = html.index("window.GM = ") + len("window.GM = ")
    return json.loads(html[debut:html.index(";\n", debut)])


# ---------- Rappels ----------
def test_analyser_texte():
    texte = ("Courses | Lait | \n"
             "Maison | Appeler le plombier | 2026-11-05T18:00:00+01:00\n"
             "\n"
             "Travail | Rapport | Q3 | 2026-11-06\n"
             "Sans liste\n"
             "Maison | Titre avec | barre | pas une date\n")
    r = analyser_texte(texte)
    assert [x["titre"] for x in r] == ["Lait", "Appeler le plombier", "Rapport | Q3", "Sans liste", "Titre avec | barre | pas une date"]
    assert r[0]["echeance"] is None and r[0]["liste"] == "Courses"
    assert r[1]["echeance"].startswith("2026-11-05T18:00") and r[1]["journee"] is False
    assert r[2]["journee"] is True
    assert r[3]["liste"] == "Rappels"


def test_analyser_json():
    r = analyser_json({"rappels": [{"liste": "Courses", "titre": "Pain"}, {"titre": " "}, "x"]})
    assert r == [{"liste": "Courses", "titre": "Pain", "echeance": None, "journee": False}]
    with pytest.raises(ValueError):
        analyser_json({"rappels": "non"})


def test_raccourci_envoie_les_rappels(appli):
    c = appli()
    assert c.post("/api/rappels", data={"texte": "Courses | Lait | "}).status_code == 403
    assert c.post("/api/rappels", data={"texte": "x", "cle": "mauvaise"}).status_code == 403
    r = c.post("/api/rappels", data={"texte": "Courses | Lait | \nMaison | Vitres | 2026-11-08"}, headers={"X-Cle": CLE})
    assert r.status_code == 200 and r.get_json()["recus"] == 2
    t = c.get("/api/tableau").get_json()
    assert [x["titre"] for x in t["rappels"]["rappels"]] == ["Lait", "Vitres"] and t["rappels"]["recu"]
    # un nouvel envoi remplace le précédent (les rappels cochés disparaissent)
    c.post("/api/rappels", json={"rappels": [{"liste": "Courses", "titre": "Pain"}]}, headers={"X-Cle": CLE})
    assert [x["titre"] for x in c.get("/api/tableau").get_json()["rappels"]["rappels"]] == ["Pain"]


def test_raccourci_sans_connexion_mais_avec_cle(appli):
    c = appli(mot_de_passe="secret")
    assert c.get("/api/tableau").status_code == 401
    assert c.post("/api/rappels", data={"texte": "A | B | "}, headers={"X-Cle": CLE}).status_code == 200


# ---------- Agenda ----------
def test_agenda_du_jour():
    http = FauxHTTP()
    a = Agenda(["https://calendar.google.com/secret/basic.ics"], session=http)
    j = a.du_jour(date(2026, 11, 5))
    titres = [e["titre"] for e in j["evenements"]]
    assert titres == ["Anniversaire de Léa", "Dentiste", "Sport"]  # journée entière d'abord, annulé et lendemain exclus
    dentiste = j["evenements"][1]
    assert dentiste["debut"] == "2026-11-05T14:30:00+01:00" and dentiste["lieu"] == "Cabinet du centre"
    assert j["evenements"][2]["debut"] == "2026-11-05T18:00:00+01:00"  # récurrence hebdomadaire, 17 h UTC = 18 h à Paris
    assert j["evenements"][0]["journee"] and j["evenements"][0]["agenda"] == "Famille"
    a.du_jour(date(2026, 11, 5))
    assert http.appels == 1  # mis en cache


def test_agenda_erreur_ne_montre_pas_l_adresse():
    a = Agenda(["https://calendar.google.com/calendar/ical/private-SECRET/basic.ics"], session=FauxHTTP(statut=404))
    j = a.du_jour(date(2026, 11, 5))
    assert j["evenements"] == [] and "SECRET" not in json.dumps(j) and "404" in j["erreurs"][0]


def test_agenda_dans_le_tableau(appli):
    agenda = Agenda(["https://x/basic.ics"], session=FauxHTTP())
    c = appli(agenda=agenda)
    j = c.get("/api/tableau").get_json()
    assert "agenda" in j and "evenements" in j["agenda"]
    assert Agenda.depuis_texte("") is None
    assert len(Agenda.depuis_texte("https://a/1.ics, https://b/2.ics").adresses) == 2


# ---------- Smart Life ----------
def test_lire_alarme():
    assert lire_alarme([{"code": "master_mode", "value": "disarmed"}])["niveau"] == "off"
    assert lire_alarme([{"code": "master_mode", "value": "home"}])["libelle"] == "Activée (présence)"
    declenchee = lire_alarme([{"code": "master_mode", "value": "arm"}, {"code": "master_state", "value": "alarm"}])
    assert declenchee["niveau"] == "alerte" and declenchee["libelle"] == "Alarme déclenchée"
    assert lire_alarme([])["niveau"] == "inconnu"


def test_alarme_et_camera(appli):
    sl, tuya = faux_smartlife()
    c = appli(smartlife=sl)
    a = c.get("/api/tableau").get_json()["alarme"]
    assert a["libelle"] == "Activée (absence)" and a["en_ligne"] is True
    c.get("/api/tableau")
    assert sum(1 for u, *_ in tuya.appels if u.endswith("/status")) == 1  # cache de 15 s
    r = c.post("/api/camera/direct")
    assert r.get_json() == {"url": "https://flux.example/live.m3u8"}
    assert ("/v1.0/devices/camera1/stream/actions/allocate", "POST", {"type": "hls"}) in tuya.appels


def test_camera_refusee(appli):
    sl, _ = faux_smartlife(flux=None)
    r = appli(smartlife=sl).post("/api/camera/direct")
    assert r.status_code == 502 and "permission deny" in r.get_json()["message"]
    assert appli().post("/api/camera/direct").status_code == 404


def test_smartlife_erreur_de_connexion(appli):
    class Casse:
        error = {"Error": "Cloud _gettoken() failed", "Err": "914"}
    sl = SmartLife("eu", "k", "s", "alarme1", None, fabrique=Casse)
    with pytest.raises(ErreurSmartLife):
        sl.etat_alarme()
    a = appli(smartlife=SmartLife("eu", "k", "s", "alarme1", None, fabrique=Casse)).get("/api/tableau").get_json()["alarme"]
    assert "gettoken" in a["erreur"]
    assert SmartLife.depuis_environnement({}) is None


# ---------- Tableau, connexion et sous-appli ----------
def test_page_tableau(appli):
    html = appli().get("/").get_data(as_text=True)
    assert "<title>Maison</title>" in html
    debut = html.index("window.MAISON = ") + len("window.MAISON = ")
    m = json.loads(html[debut:html.index(";</script>", debut)])
    assert m["raccourci"]["cle"] == CLE and m["raccourci"]["adresse"].endswith("/api/rappels")
    assert m["agenda"] is False and m["camera"] is False


def test_garde_manger_sous_appli(appli):
    c = appli()
    assert c.get("/garde-manger").status_code == 308
    r = c.get("/garde-manger/")
    assert r.status_code == 200 and gm_injecte(r.get_data(as_text=True))["retour"] == "../"
    assert c.put("/garde-manger/api/etat", json={"etat": {"courses": [{"id": "lait", "label": "Lait"}],
                                                           "pantry": [{"id": "courgette", "label": "Courgettes", "urgent": True}]}}).status_code == 200
    gm = c.get("/api/tableau").get_json()["garde_manger"]
    assert gm == {"courses": ["Lait"], "a_finir": ["Courgettes"], "placard": 1}
    assert c.get("/garde-manger/static/apple-touch-icon.png").status_code == 200


def test_une_seule_connexion(appli):
    c = appli(mot_de_passe="secret")
    assert c.get("/").headers["Location"].endswith("/connexion")
    assert c.get("/garde-manger/").headers["Location"] == "/connexion"
    assert c.get("/garde-manger/api/etat").status_code == 401
    assert "Mot de passe incorrect" in c.post("/connexion", data={"mot_de_passe": "non"}).get_data(as_text=True)
    assert c.post("/connexion", data={"mot_de_passe": "secret"}).status_code == 302
    assert c.get("/").status_code == 200
    assert c.get("/garde-manger/").status_code == 200  # connecté partout
    assert c.get("/garde-manger/api/etat").status_code == 200
    c.post("/deconnexion")
    assert c.get("/api/tableau").status_code == 401


def test_trop_d_essais(appli):
    c = appli(mot_de_passe="secret")
    for _ in range(5):
        c.post("/connexion", data={"mot_de_passe": "non"})
    r = c.post("/connexion", data={"mot_de_passe": "secret"})
    assert "Trop d'essais" in r.get_data(as_text=True)
