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


def test_reglages_et_anciennes_cles_effacees(tmp_path):
    coffre = plateforme.CoffreFichier(str(tmp_path / "coffre.json"))
    coffre.ecrire({"smartlife_cle": "ID", "smartlife_secret": "SECRET", "smartlife_alarme": "al1", "ville": "Lyon"})
    a = appli_locale.Appli(str(tmp_path / "d"), plateforme.RappelsSimules(str(tmp_path / "r.json")), None, coffre)
    assert coffre.lire() == {"ville": "Lyon"}  # Smart Life retiré : clés effacées du trousseau
    r = a.enregistrer_reglages({"ville": "Brest", "liste_courses": "Épicerie", "agenda_ical": "https://x/basic.ics"})
    assert r == {"ville": "Brest", "liste_courses": "Épicerie", "agenda_ical": True}
    assert "https://x" not in json.dumps(r)  # l'adresse iCal secrète ne revient pas à la page
    a.enregistrer_reglages({"agenda_ical": ""})
    assert coffre.lire()["agenda_ical"] == "https://x/basic.ics"  # vide = conservée


# ---------- Rappels simulés ----------
def test_rappels_simules(tmp_path):
    r = plateforme.RappelsSimules(str(tmp_path / "r.json"), listes=("Courses", "Maison"))
    with pytest.raises(plateforme.ListeIntrouvable):
        r.ajouter("Inexistante", "x")
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
    rappels = plateforme.RappelsSimules(str(tmp_path / "rappels.json"), listes=("Maison", "Courses"))
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


def test_meteo_dans_les_reglages(appli):
    a, c, _, _ = appli
    assert injecte(c.appel("GET", "/")[1], "MAISON")["meteo"] is False
    assert c.json("POST", "/api/reglages", {"ville": "Lyon"})[1]["ville"] == "Lyon"
    assert injecte(c.appel("GET", "/")[1], "MAISON")["meteo"] is True
    sys.path.insert(0, os.path.join(ICI, "tests"))
    from meteo import Meteo
    from test_maison import FauxMeteoHTTP
    a._meteo = Meteo("Lyon", session=FauxMeteoHTTP())
    assert c.json("GET", "/api/tableau")[1]["meteo"]["jours"][1]["libelle"] == "Éclaircies"


def test_liste_de_courses_choisie(appli):
    a, c, rappels, _ = appli
    rappels.creer_liste("買い物リスト")
    rappels.ajouter("買い物リスト", "牛乳")
    _, d = c.json("GET", "/api/rappels/listes")
    assert {l["nom"]: l["nombre"] for l in d["listes"]} == {"Maison": 1, "Courses": 0, "買い物リスト": 1} and d["trouvee"]
    c.json("POST", "/api/reglages", {"liste_courses": "買い物リスト"})
    _, d = c.json("GET", "/api/rappels/listes")
    assert d["courses"] == "買い物リスト" and d["trouvee"]
    assert c.json("POST", "/garde-manger/api/courses/rappels", {"ajouter": [{"titre": "Œufs"}]})[1]["ajoutes"] == 1
    assert {x["titre"] for x in rappels.lire() if x["liste"] == "買い物リスト"} == {"牛乳", "Œufs"}
    # une liste mal nommée n'est plus créée : message clair
    c.json("POST", "/api/reglages", {"liste_courses": "買い物のリスタート"})
    assert c.json("GET", "/api/rappels/listes")[1]["trouvee"] is False
    r = c.json("POST", "/garde-manger/api/courses/rappels", {"ajouter": [{"titre": "Pain"}]})[1]
    assert r["ajoutes"] == 0 and "introuvable" in r["erreur"]
    assert "買い物のリスタート" not in {l["nom"] for l in rappels.listes()}


# ---------- Rappels de l'iPhone, avec un faux module « reminders » de Pythonista ----------
class FauxReminders:
    class Calendar:
        def __init__(self, title=""):
            self.title = title

    def __init__(self):
        self.listes = [self.Calendar("Maison"), self.Calendar("買い物リスト"), self.Calendar("Cassée")]
        self.items = {"Maison": [], "買い物リスト": [], "Cassée": []}
        test = self

        class Reminder:
            def __init__(self, calendar=None):
                self.calendar, self.title, self.completed, self.due_date = calendar, "", False, None

            def save(self):
                if self not in test.items[self.calendar.title]:
                    test.items[self.calendar.title].append(self)
        self.Reminder = Reminder

    def get_all_calendars(self):
        return list(self.listes)

    def get_reminders(self, calendar=None, completed=None):
        if calendar.title == "Cassée":
            raise RuntimeError("liste partagée indisponible")
        return [r for r in self.items[calendar.title] if completed is None or r.completed == completed]

    def get_default_calendar(self):
        return self.listes[0]


def test_rappels_ios_avec_faux_module(monkeypatch):
    from datetime import date
    faux = FauxReminders()
    monkeypatch.setitem(sys.modules, "reminders", faux)
    r = plateforme.RappelsIOS()
    assert r.ajouter("買い物リスト", "牛乳") and r.ajouter("maison", "Vitres")  # nom de liste sans tenir compte des majuscules
    faux.items["Maison"][0].due_date = date(2026, 11, 5)  # échéance sans heure
    lus = r.lire()
    assert {(x["liste"], x["titre"]) for x in lus} == {("買い物リスト", "牛乳"), ("Maison", "Vitres")}
    assert next(x for x in lus if x["titre"] == "Vitres")["journee"] is True
    assert r.erreurs == ["Liste « Cassée » illisible (RuntimeError)"]  # les autres listes restent lisibles
    assert {l["nom"]: (l["nombre"], l["erreur"]) for l in r.listes()} == {"Maison": (1, None), "買い物リスト": (1, None), "Cassée": (None, "RuntimeError")}
    assert r.terminer(next(x["id"] for x in lus if x["titre"] == "牛乳"))
    assert [x["titre"] for x in r.lire()] == ["Vitres"]
    with pytest.raises(plateforme.ListeIntrouvable):
        r.ajouter("買い物のリスタート", "Pain")
    assert len(faux.listes) == 3  # aucune liste créée


def test_menage_version_pythonista(appli):
    _, c, _, _ = appli
    d = c.json("GET", "/api/tableau")[1]["menage"]
    t = d["taches"][0]["id"]
    assert c.json("POST", "/api/menage/cocher", {"tache": t, "date": "2026-11-07"}) == (200, {"fait": [t]})
    assert c.json("POST", "/api/menage/cocher", {"tache": t, "date": "hier"})[0] == 400
    statut, r = c.json("PUT", "/api/menage/taches", {"taches": [{"piece": "cuisine", "titre": "Poubelles", "jours": [1, 4]}]})
    assert statut == 200 and r["taches"][0]["jours"] == [1, 4]


# ---------- Code-barres (version Pythonista) ----------
class FauxOFF:
    def chercher(self, texte):
        from codes_barres import ErreurCode, code_valide
        if not code_valide(texte):
            raise ErreurCode("invalide", "invalide")
        return {"code": texte, "trouve": True, "nom": "Vinaigre de cidre"}


class FauxScanner:
    def __init__(self, resultats):
        self.resultats = list(resultats)

    def scanner(self):
        r = self.resultats.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_code_barres_version_pythonista(tmp_path):
    rappels = plateforme.RappelsSimules(str(tmp_path / "rappels.json"))
    coffre = plateforme.CoffreFichier(str(tmp_path / "coffre.json"))
    scanner = FauxScanner(["3564700013342", None, ValueError("Aucun code-barres lu"), "https://exemple.fr"])
    a = appli_locale.Appli(str(tmp_path / "d"), rappels, None, coffre, scanner=scanner, off=FauxOFF())
    serveur, adresse = appli_locale.demarrer(a)
    try:
        c = Client(adresse)
        gm = injecte(c.appel("GET", "/garde-manger/")[1], "GM")
        assert gm["codes"] is True and gm["scanner"] is True
        assert c.json("GET", "/garde-manger/api/code/3564700013342")[1]["nom"] == "Vinaigre de cidre"
        assert c.json("GET", "/garde-manger/api/code/123")[0] == 400
        assert c.json("POST", "/garde-manger/api/scanner", {}) == (200, {"code": "3564700013342"})
        assert c.json("POST", "/garde-manger/api/scanner", {}) == (200, {"annule": True})
        assert c.json("POST", "/garde-manger/api/scanner", {})[1] == {"erreur": "Aucun code-barres lu"}
        assert "n'est pas un code-barres" in c.json("POST", "/garde-manger/api/scanner", {})[1]["erreur"]
    finally:
        serveur.shutdown()


def test_sans_scanner(appli):
    _, c, _, _ = appli
    assert injecte(c.appel("GET", "/garde-manger/")[1], "GM")["scanner"] is False
    assert c.json("POST", "/garde-manger/api/scanner", {})[0] == 404


# ---------- Synchronisation iPhone / iPad ----------
class FauxICloud:
    def __init__(self):
        self.demandes = []

    def rafraichir(self, chemin):
        self.demandes.append(os.path.basename(chemin))


def test_synchronisation_entre_appareils(tmp_path):
    icloud = FauxICloud()
    coffre = plateforme.CoffreFichier(str(tmp_path / "coffre.json"))
    a = appli_locale.Appli(str(tmp_path / "d"), plateforme.RappelsSimules(str(tmp_path / "r.json")), None, coffre,
                           icloud=icloud, appareil="iPad", partage="icloud")
    serveur, adresse = appli_locale.demarrer(a)
    try:
        c = Client(adresse)
        assert injecte(c.appel("GET", "/")[1], "MAISON")["synchro"] == {"partage": "icloud", "appareil": "iPad"}
        assert c.json("PUT", "/garde-manger/api/etat", {"etat": {"pantry": []}, "version": 0})[1]["version"] == 1
        assert c.json("PUT", "/garde-manger/api/etat", {"etat": {"pantry": [1]}, "version": 0}) == (409, {"code": "conflit", "version": 1})
        placard = c.json("GET", "/api/tableau")[1]["synchro"]["placard"]
        assert placard["appareil"] == "iPad" and placard["date"] and placard["en_attente"] is False
        assert "etat.json" in icloud.demandes and "menage.json" in icloud.demandes
        # fichier pas encore descendu d'iCloud : rien n'est écrasé
        os.remove(tmp_path / "d" / "garde-manger" / "etat.json")
        (tmp_path / "d" / "garde-manger" / ".etat.json.icloud").write_bytes(b"")
        assert c.json("PUT", "/garde-manger/api/etat", {"etat": {"pantry": []}, "version": 0})[0] == 503
        (tmp_path / "d" / ".menage.json.icloud").write_bytes(b"")
        t = c.json("GET", "/api/tableau")[1]["menage"]["taches"][0]["id"]
        assert c.json("POST", "/api/menage/cocher", {"tache": t, "date": "2026-11-09"})[0] == 400
        assert not (tmp_path / "d" / "menage.json").exists()
    finally:
        serveur.shutdown()
