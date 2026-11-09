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


@pytest.fixture
def appli(tmp_path):
    def fabrique(**kw):
        params = dict(dossier_donnees=str(tmp_path), mot_de_passe="", cle_raccourci=CLE, agenda=None, claude=None, meteo=None)
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


# ---------- Tableau, connexion et sous-appli ----------
def test_page_tableau(appli):
    html = appli().get("/").get_data(as_text=True)
    assert "<title>Maison</title>" in html
    debut = html.index("window.MAISON = ") + len("window.MAISON = ")
    m = json.loads(html[debut:html.index(";</script>", debut)])
    assert m["raccourci"]["cle"] == CLE and m["raccourci"]["adresse"].endswith("/api/rappels")
    assert m["agenda"] is False and "camera" not in m and "alarme" not in m
    assert appli().post("/api/camera/direct").status_code in (404, 405)  # caméra retirée


def test_garde_manger_sous_appli(appli):
    c = appli()
    assert c.get("/garde-manger").status_code == 308
    r = c.get("/garde-manger/")
    assert r.status_code == 200 and gm_injecte(r.get_data(as_text=True))["retour"] == "../"
    assert c.put("/garde-manger/api/etat", json={"etat": {"courses": [{"id": "lait", "label": "Lait"}],
                                                           "pantry": [{"id": "courgette", "label": "Courgettes", "urgent": True}]}}).status_code == 200
    gm = c.get("/api/tableau").get_json()["garde_manger"]
    assert {k: gm[k] for k in ("courses", "a_finir", "placard", "peremption")} == {"courses": ["Lait"], "a_finir": ["Courgettes"], "placard": 1, "peremption": []}
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


# ---------- Météo ----------
GEO = {"results": [{"name": "Lyon", "latitude": 45.75, "longitude": 4.85}]}
PREV = {"current": {"temperature_2m": 12.4, "weather_code": 61},
        "daily": {"time": ["2026-11-05", "2026-11-06"], "weather_code": [63, 2],
                  "temperature_2m_max": [14.2, 16.8], "temperature_2m_min": [7.1, 6.0],
                  "precipitation_probability_max": [80, 10]}}


class FauxMeteoHTTP:
    def __init__(self, geo=GEO, statut=200):
        self.geo, self.statut, self.appels = geo, statut, []

    def get(self, url, params=None, timeout=None):
        import requests
        self.appels.append((url, params))
        r = requests.Response()
        r.status_code = self.statut
        r._content = json.dumps(self.geo if "geocoding" in url else PREV).encode()
        return r


def test_meteo():
    from meteo import Meteo
    http = FauxMeteoHTTP()
    m = Meteo("Lyon", session=http).previsions()
    assert m["lieu"] == "Lyon" and m["maintenant"] == {"temperature": 12.4, "libelle": "Pluie faible", "icone": "pluie"}
    assert [j["libelle"] for j in m["jours"]] == ["Pluie", "Éclaircies"] and m["jours"][1]["min"] == 6.0 and m["jours"][0]["pluie"] == 80
    params = http.appels[1][1]
    assert params["latitude"] == 45.75 and params["forecast_days"] == 2
    Meteo("Lyon", session=http)  # nouvelle instance : nouveau géocodage
    assert len(http.appels) == 2


def test_meteo_erreurs(appli):
    from meteo import ErreurMeteo, Meteo
    with pytest.raises(ErreurMeteo, match="introuvable"):
        Meteo("Xyzzy", session=FauxMeteoHTTP(geo={"results": []})).previsions()
    with pytest.raises(ErreurMeteo, match="injoignable"):
        Meteo("Lyon", session=FauxMeteoHTTP(statut=500)).previsions()
    assert Meteo.depuis_texte("  ") is None
    c = appli(meteo=Meteo("Lyon", session=FauxMeteoHTTP()))
    assert c.get("/api/tableau").get_json()["meteo"]["lieu"] == "Lyon"
    c = appli(meteo=Meteo("Xyzzy", session=FauxMeteoHTTP(geo={})))
    assert "introuvable" in c.get("/api/tableau").get_json()["meteo"]["erreur"]


# ---------- Ménage ----------
def test_menage_planning_et_cocher(tmp_path):
    from menage import Menage, PLAN
    m = Menage(str(tmp_path / "menage.json"))
    d = m.lire()
    assert {p["id"] for p in d["plan"]["pieces"]} == {"ayami", "parent", "wc", "couloir", "sdb", "entree", "cuisine"}
    assert d["taches"] and all(t["piece"] in {p["id"] for p in PLAN["pieces"]} for t in d["taches"])
    premiere = d["taches"][0]["id"]
    assert m.cocher(premiere, "2026-11-07") == [premiere]
    assert m.cocher(premiere, "2026-11-07", fait=False) == []
    m.cocher(premiere, "2026-11-07")
    assert m.lire()["fait"] == {"2026-11-07": [premiere]}
    with pytest.raises(ValueError):
        m.cocher("inconnue", "2026-11-07")
    with pytest.raises(ValueError):
        m.cocher(premiere, "7/11/2026")
    # les vieilles tâches cochées sont oubliées
    m.cocher(premiere, "2026-01-01")
    assert "2026-01-01" in m.lire()["fait"] and "2026-11-07" in m.lire()["fait"]
    m.cocher(premiere, "2026-11-08")
    assert "2026-01-01" not in m.lire()["fait"]


def test_menage_modifier_le_planning(tmp_path):
    from menage import Menage
    m = Menage(str(tmp_path / "menage.json"))
    premiere = m.lire()["taches"][0]["id"]
    m.cocher(premiere, "2026-11-07")
    taches = m.enregistrer_taches([
        {"id": premiere, "piece": "cuisine", "titre": " Vaisselle ", "jours": [6, 0, 0, "3", 9]},
        {"piece": "sdb", "titre": "Miroir", "jours": [2]},
        {"piece": "garage", "titre": "Pièce inconnue", "jours": [1]},
        {"piece": "wc", "titre": "", "jours": [1]},
        {"piece": "wc", "titre": "Sans jour", "jours": []},
    ])
    assert [(t["piece"], t["titre"], t["jours"]) for t in taches] == [("cuisine", "Vaisselle", [0, 3, 6]), ("sdb", "Miroir", [2])]
    assert taches[0]["id"] == premiere and taches[1]["id"].startswith("t")
    assert m.lire()["fait"]["2026-11-07"] == [premiere]
    m.enregistrer_taches([{"piece": "sdb", "titre": "Miroir", "jours": [2]}])
    assert m.lire()["fait"].get("2026-11-07", []) == []  # tâche supprimée : plus cochée


def test_menage_dans_le_tableau(appli):
    c = appli()
    d = c.get("/api/tableau").get_json()["menage"]
    t = d["taches"][0]["id"]
    assert c.post("/api/menage/cocher", json={"tache": t, "date": "2026-11-07"}).get_json() == {"fait": [t]}
    assert c.post("/api/menage/cocher", json={"tache": t}).status_code == 400
    r = c.put("/api/menage/taches", json={"taches": [{"piece": "wc", "titre": "Toilettes", "jours": [5]}]})
    assert r.status_code == 200 and c.get("/api/tableau").get_json()["menage"]["taches"][0]["titre"] == "Toilettes"
    assert c.put("/api/menage/taches", json={"taches": "non"}).status_code == 400


# ---------- Semaine : agenda et météo détaillée ----------
def test_agenda_semaine():
    a = Agenda(["https://calendar.google.com/secret/basic.ics"], session=FauxHTTP())
    s = a.semaine(date(2026, 11, 5))
    assert s["debut"] == "2026-11-05" and len(s["jours"]) == 7 and s["erreurs"] == []
    assert [e["titre"] for e in s["jours"][0]["evenements"]] == ["Anniversaire de Léa", "Dentiste", "Sport"]
    assert s["jours"][1]["jour"] == "2026-11-06" and s["jours"][1]["evenements"]  # le rendez-vous du lendemain


def test_repartir_par_jour():
    from liens import repartir_par_jour
    evs = [{"titre": "Vacances", "debut": "2026-11-06", "fin": "2026-11-09", "journee": True},
           {"titre": "Nuit blanche", "debut": "2026-11-05T22:00:00+01:00", "fin": "2026-11-06T02:00:00+01:00", "journee": False},
           {"titre": "Hors période", "debut": "2026-12-01T10:00:00+01:00", "fin": "2026-12-01T11:00:00+01:00", "journee": False},
           {"titre": "Abîmé", "debut": "pas une date", "journee": False}]
    jours = repartir_par_jour(evs, date(2026, 11, 5), 7)
    noms = [[e["titre"] for e in j["evenements"]] for j in jours]
    assert noms[0] == ["Nuit blanche"] and noms[1] == ["Vacances", "Nuit blanche"] and noms[3] == ["Vacances"] and noms[4] == []
    assert jours[1]["evenements"][1]["suite"] is True and "suite" not in jours[0]["evenements"][0]


SEMAINE = {
    "daily": {"time": [f"2026-11-{5 + i:02d}" for i in range(7)], "weather_code": [63, 2, 0, 3, 61, 95, 71],
              "temperature_2m_max": [14, 16, 17, 12, 11, 10, 2], "temperature_2m_min": [7, 6, 5, 4, 3, 2, -1],
              "precipitation_probability_max": [80, 10, 0, 20, 70, 90, 60], "precipitation_sum": [6.2, 0, 0, 0.3, 4, 12, 3],
              "wind_speed_10m_max": [20, 10, 8, 15, 30, 45, 25], "wind_gusts_10m_max": [40, 20, 15, 30, 60, 80, 45],
              "uv_index_max": [1, 2, 3, 1, 1, 0, 1], "sunrise": ["2026-11-05T07:42"] * 7, "sunset": ["2026-11-05T17:21"] * 7},
    "hourly": {"time": [f"2026-11-05T{h:02d}:00" for h in range(24)] + ["2026-11-06T00:00"],
               "temperature_2m": list(range(25)), "apparent_temperature": list(range(25)), "weather_code": [61] * 25,
               "precipitation_probability": [50] * 25, "precipitation": [0.4] * 25, "wind_speed_10m": [12] * 25},
}


def test_meteo_semaine(appli):
    from meteo import Meteo

    class Http(FauxMeteoHTTP):
        def get(self, url, params=None, timeout=None):
            r = super().get(url, params, timeout)
            if "geocoding" not in url:
                r._content = json.dumps(SEMAINE).encode()
            return r
    http = Http()
    s = Meteo("Lyon", session=http).semaine()
    assert http.appels[1][1]["forecast_days"] == 7
    assert len(s["jours"]) == 7 and s["jours"][5]["libelle"] == "Orage" and s["jours"][5]["rafales"] == 80
    j = s["jours"][0]
    assert j["lever"] == "07:42" and j["coucher"] == "17:21" and j["pluie_mm"] == 6.2
    assert len(j["heures"]) == 24 and j["heures"][14] == {"heure": "14:00", "temperature": 14, "ressenti": 14, "libelle": "Pluie faible",
                                                         "icone": "pluie", "pluie": 50, "pluie_mm": 0.4, "vent": 12}
    assert len(s["jours"][1]["heures"]) == 1 and s["jours"][2]["heures"] == []
    c = appli(meteo=Meteo("Lyon", session=Http()), agenda=Agenda(["https://x/basic.ics"], session=FauxHTTP()))
    assert len(c.get("/api/meteo/semaine").get_json()["jours"]) == 7
    assert len(c.get("/api/agenda/semaine").get_json()["jours"]) == 7
    c = appli()
    assert "MAISON_VILLE" in c.get("/api/meteo/semaine").get_json()["erreur"]


def test_agenda_ical_choix_des_calendriers():
    a = Agenda(["https://calendar.google.com/secret/basic.ics", "https://calendar.google.com/autre/basic.ics"], session=FauxHTTP())
    assert [c["id"] for c in a.calendriers()] == ["ical-1", "ical-2"] and a.calendriers()[0]["nom"] == "Famille"
    tous = len(a.du_jour(date(2026, 11, 5))["evenements"])
    a.choisis = {"ical-1"}
    assert len(a.du_jour(date(2026, 11, 5))["evenements"]) == tous // 2
