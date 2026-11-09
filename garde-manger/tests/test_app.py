import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import donnees  # noqa: E402
from app import create_app  # noqa: E402
from construire_page import construire  # noqa: E402
from service_claude import ErreurClaude, consigne_idees, consigne_plat, lire_json  # noqa: E402


class FauxClaude:
    """Remplace Claude pendant les tests : aucune requête ne part sur Internet."""

    def __init__(self):
        self.appels = []

    def recette(self, nom, personnes, ustensiles):
        self.appels.append(("plat", nom, personnes, ustensiles))
        return {"nom": nom.capitalize(), "portions": personnes, "ingredients": [{"nom": "veau", "quantite": "600 g"}], "etapes": ["Cuire."]}

    def idees(self, placard, personnes, ustensiles, filtres, deja):
        self.appels.append(("idees", placard, personnes, filtres, deja))
        return [{"nom": "Omelette", "ingredients": [], "etapes": []}]

    def produits_sur_photo(self, image, type_image):
        self.appels.append(("photo", len(image), type_image))
        if type_image != "image/jpeg":
            raise ErreurClaude("image_rejected", "format", 400)
        return ["œufs", "lait"]


@pytest.fixture
def client(tmp_path):
    app = create_app(dossier_donnees=str(tmp_path), mot_de_passe="", claude=None)
    return app.test_client()


@pytest.fixture
def faux():
    return FauxClaude()


@pytest.fixture
def client_claude(tmp_path, faux):
    return create_app(dossier_donnees=str(tmp_path), mot_de_passe="", claude=faux).test_client()


def donnees_injectees(html):
    debut = html.index("window.GM = ") + len("window.GM = ")
    fin = html.index(";\n", debut)
    return json.loads(html[debut:fin])


def test_page_contient_les_donnees(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "<title>Garde-manger</title>" in html
    gm = donnees_injectees(html)
    assert len(gm["donnees"]["recettes"]) == len(donnees.RECETTES)
    assert gm["claude"] is False
    assert gm["version"] == 0 and gm["etat"] == {}


def test_donnees_coherentes():
    cles = {k for k, *_ in donnees.PRODUITS}
    assert len(cles) == len(donnees.PRODUITS), "clé de produit en double"
    for r in donnees.RECETTES:
        for ing in r["ingredients"]:
            assert ing.lstrip("?").split(":")[0] in cles, (r["nom"], ing)
        assert 1 <= r["difficulte"] <= 3
        assert r["preparation"] <= r["minutes"]
        assert r["etapes"]


def test_etat_partage_entre_appareils(client):
    etat = {"pantry": [{"id": "oeuf", "label": "Œufs", "urgent": False, "n": 6, "u": "pc"}], "tools": ["four"]}
    r = client.put("/api/etat", json={"etat": etat})
    assert r.status_code == 200 and r.get_json()["version"] == 1
    assert client.get("/api/etat").get_json() == {"version": 1, "etat": etat}
    assert client.put("/api/etat", json={"etat": {}}).get_json()["version"] == 2
    assert client.get("/api/etat/version").get_json()["version"] == 2
    # la page rouverte (sur un autre appareil) reçoit l'état enregistré
    client.put("/api/etat", json={"etat": etat})
    assert donnees_injectees(client.get("/").get_data(as_text=True))["etat"] == etat


def test_etat_invalide_refuse(client):
    assert client.put("/api/etat", json={"etat": [1, 2]}).status_code == 400
    assert client.put("/api/etat", data="pas du json").status_code == 400
    assert client.put("/api/etat", json={"etat": {"x": "a" * 1_100_000}}).status_code == 413


def test_etat_survit_au_redemarrage(tmp_path):
    a = create_app(dossier_donnees=str(tmp_path), mot_de_passe="", claude=None).test_client()
    a.put("/api/etat", json={"etat": {"courses": [{"id": "lait", "label": "Lait"}]}})
    b = create_app(dossier_donnees=str(tmp_path), mot_de_passe="", claude=None).test_client()
    assert b.get("/api/etat").get_json()["etat"]["courses"][0]["id"] == "lait"


def test_claude_absent(client):
    r = client.post("/api/claude/plat", json={"nom": "quiche"})
    assert r.status_code == 503 and r.get_json()["code"] == "indisponible"


def test_claude_plat(client_claude, faux):
    r = client_claude.post("/api/claude/plat", json={"nom": "  blanquette  ", "personnes": 40, "ustensiles": ["Four", 3]})
    assert r.status_code == 200
    assert r.get_json()["recette"]["nom"] == "Blanquette"
    assert faux.appels[-1] == ("plat", "blanquette", 12, ["Four", "3"])
    assert client_claude.post("/api/claude/plat", json={"nom": ""}).status_code == 400


def test_claude_idees(client_claude, faux):
    corps = {"placard": [{"nom": "Œufs", "quantite": "6", "a_finir": True}, {"bad": 1}], "personnes": 3,
             "filtres": {"vegetarien": True, "type": "n'importe quoi"}, "deja": ["Crêpes"]}
    r = client_claude.post("/api/claude/idees", json=corps)
    assert r.status_code == 200 and r.get_json()["recettes"][0]["nom"] == "Omelette"
    _, placard, personnes, filtres, deja = faux.appels[-1]
    assert placard == [{"nom": "Œufs", "quantite": "6", "a_finir": True}]
    assert personnes == 3 and filtres["type"] == "tout" and filtres["vegetarien"] and deja == ["Crêpes"]
    assert client_claude.post("/api/claude/idees", json={"placard": []}).status_code == 400


def test_claude_photo(client_claude):
    r = client_claude.post("/api/claude/photo", data={"image": (io.BytesIO(b"\xff\xd8jpeg"), "photo.jpg", "image/jpeg")})
    assert r.status_code == 200 and r.get_json()["produits"] == ["œufs", "lait"]
    r = client_claude.post("/api/claude/photo", data={"image": (io.BytesIO(b"GIF8"), "x.bmp", "image/bmp")})
    assert r.status_code == 400 and r.get_json()["code"] == "image_rejected"
    assert client_claude.post("/api/claude/photo").status_code == 400


def test_mot_de_passe(tmp_path):
    c = create_app(dossier_donnees=str(tmp_path), mot_de_passe="secret", claude=None).test_client()
    assert c.get("/").status_code == 302
    assert c.get("/api/etat").status_code == 401
    assert c.get("/static/apple-touch-icon.png").status_code == 200
    assert c.get("/manifest.webmanifest").status_code == 200
    r = c.post("/connexion", data={"mot_de_passe": "faux"})
    assert "Mot de passe incorrect" in r.get_data(as_text=True)
    assert c.post("/connexion", data={"mot_de_passe": "secret"}).status_code == 302
    assert c.get("/").status_code == 200
    assert c.get("/api/etat").status_code == 200


def test_texte_ne_ferme_pas_le_script(client):
    client.put("/api/etat", json={"etat": {"pantry": [{"id": "x:a", "label": "</script><b>"}]}})
    html = client.get("/").get_data(as_text=True)
    assert "</script><b>" not in html


def test_lire_json():
    assert lire_json('{"a": 1}') == {"a": 1}
    assert lire_json('Voici :\n```json\n[1, 2]\n```') == [1, 2]
    assert lire_json('Bien sûr ! {"nom": "Quiche"} Bon appétit') == {"nom": "Quiche"}
    with pytest.raises(ErreurClaude):
        lire_json("pas de json ici")


def test_consignes():
    assert "pour 1 personne." in consigne_plat("quiche", 1, [])
    texte = consigne_idees([{"nom": "Œufs", "quantite": "6", "a_finir": True}], 2, ["Four"],
                           {"vegetarien": True, "type": "dessert"}, ["Crêpes"])
    assert "Œufs (6)" in texte and "À utiliser en priorité" in texte
    assert "végétarien ; uniquement des desserts" in texte and "Crêpes" in texte


def test_page_statique_pour_github_pages(tmp_path):
    appli = construire(str(tmp_path / "_site"))
    html = open(os.path.join(appli, "index.html"), encoding="utf-8").read()
    gm = donnees_injectees(html)
    assert gm["statique"] is True and gm["claude"] is False and gm["etat"] == {}
    assert len(gm["donnees"]["recettes"]) == len(donnees.RECETTES)
    for fichier in ["manifest.webmanifest", "sw.js", "static/apple-touch-icon.png", "static/icone-512.png"]:
        assert os.path.isfile(os.path.join(appli, fichier)), fichier
    manifeste = json.load(open(os.path.join(appli, "manifest.webmanifest"), encoding="utf-8"))
    # chemins relatifs : la page vit dans un sous-dossier de github.io
    assert manifeste["start_url"] == "./" and not manifeste["icons"][0]["src"].startswith("/")
    assert os.path.isfile(tmp_path / "_site" / ".nojekyll")
    assert "garde-manger/" in open(tmp_path / "_site" / "index.html", encoding="utf-8").read()


def test_catalogue_de_produits():
    noms = {nom: (cle, rayon, alias) for cle, nom, rayon, alias in donnees.PRODUITS}
    assert len(donnees.PRODUITS) >= 290
    for nom in ["Fromage à raclette", "Pâte à tartiner", "Chocolat en poudre", "Confiture de fraises", "Sodas", "Café"]:
        assert nom in noms, nom
    assert "nutella" in noms["Pâte à tartiner"][2] and "nesquik" in noms["Chocolat en poudre"][2]
    assert {rayon for _, _, rayon, _ in donnees.PRODUITS} <= set(donnees.RAYONS)
    assert donnees.pour_interface()["rayons"] == donnees.RAYONS


# ---------- Codes-barres ----------
from codes_barres import ErreurCode, OpenFoodFacts, code_valide  # noqa: E402


class FausseReponse:
    def __init__(self, statut, donnees):
        self.status_code, self._donnees = statut, donnees

    def json(self):
        return self._donnees


class FausseSession:
    def __init__(self, reponses):
        self.reponses, self.appels = dict(reponses), []

    def get(self, adresse, params=None, headers=None, timeout=None):
        self.appels.append(adresse)
        reponse = self.reponses.get(adresse.rsplit("/", 1)[1].split(".")[0])
        if isinstance(reponse, Exception):
            raise reponse
        return reponse or FausseReponse(404, {"status": 0})


VINAIGRE = {"status": 1, "product": {"product_name_fr": "Vinaigre de cidre", "brands": "Rustica,Carrefour",
                                     "quantity": "75 cl", "categories": "Condiments, Vinaigres, Vinaigres de cidre"}}


def test_code_valide():
    assert code_valide("3564700013342") == "3564700013342"
    assert code_valide("3 017620 422003") == "3017620422003"
    assert code_valide("3564700013343") is None  # mauvaise clé de contrôle
    assert code_valide("012345678905") == "0012345678905"  # UPC-A
    assert code_valide("96385074") == "96385074"  # EAN-8
    assert code_valide("123") is None and code_valide(None) is None


def test_open_food_facts_avec_fausse_session():
    import requests
    session = FausseSession({"3564700013342": FausseReponse(200, VINAIGRE),
                             "3017620422003": requests.ConnectionError("hors ligne")})
    off = OpenFoodFacts(session)
    f = off.chercher("3564700013342")
    assert f["trouve"] and f["nom"] == "Vinaigre de cidre" and f["marque"] == "Rustica" and f["quantite"] == "75 cl"
    assert f["categories"][-1] == "Vinaigres de cidre"
    off.chercher("3564700013342")
    assert len(session.appels) == 1  # gardé en mémoire
    assert off.chercher("96385074") == {"code": "96385074", "trouve": False}
    with pytest.raises(ErreurCode) as e:
        off.chercher("3017620422003")
    assert e.value.code == "reseau"
    with pytest.raises(ErreurCode) as e:
        off.chercher("3564700013343")
    assert e.value.code == "invalide"


def test_route_code_barres(tmp_path):
    import requests
    session = FausseSession({"3564700013342": FausseReponse(200, VINAIGRE),
                             "3017620422003": requests.Timeout()})
    c = create_app(dossier_donnees=str(tmp_path), mot_de_passe="", claude=None, off=OpenFoodFacts(session)).test_client()
    r = c.get("/api/code/3564700013342")
    assert r.status_code == 200 and r.get_json()["nom"] == "Vinaigre de cidre"
    assert c.get("/api/code/3564700013343").status_code == 400
    assert c.get("/api/code/3017620422003").status_code == 502


# ---------- Synchronisation entre appareils ----------
from stockage import EnAttenteICloud, Stockage, VersionDepassee  # noqa: E402


def test_stockage_ne_jamais_ecraser_l_autre_appareil(tmp_path):
    lus = []
    iphone = Stockage(str(tmp_path / "etat.json"), avant_lecture=lus.append, appareil="iPhone")
    ipad = Stockage(str(tmp_path / "etat.json"), appareil="iPad")
    assert iphone.ecrire({"pantry": [1]}, base=0) == 1
    assert ipad.ecrire({"pantry": [1, 2]}, base=1) == 2
    with pytest.raises(VersionDepassee) as e:
        iphone.ecrire({"pantry": []}, base=1)  # l'iPhone n'a pas vu l'ajout de l'iPad
    assert e.value.version == 2 and iphone.lire() == (2, {"pantry": [1, 2]})
    assert iphone.ecrire({"pantry": [3]}) == 3  # sans version : le dernier gagne (anciennes pages)
    infos = iphone.infos()
    assert infos["appareil"] == "iPhone" and infos["date"] and infos["en_attente"] is False
    assert lus and all(c.endswith("etat.json") for c in lus)  # téléchargement iCloud demandé avant lecture


def test_stockage_attend_icloud(tmp_path):
    (tmp_path / ".etat.json.icloud").write_bytes(b"")  # fichier pas encore téléchargé sur cet appareil
    s = Stockage(str(tmp_path / "etat.json"))
    assert s.lire() == (0, {}) and s.infos()["en_attente"] is True
    with pytest.raises(EnAttenteICloud):
        s.ecrire({"pantry": []}, base=0)
    assert not (tmp_path / "etat.json").exists()


def test_route_etat_conflit(client):
    assert client.put("/api/etat", json={"etat": {"a": 1}, "version": 0}).get_json()["version"] == 1
    r = client.put("/api/etat", json={"etat": {"a": 2}, "version": 0})
    assert r.status_code == 409 and r.get_json() == {"code": "conflit", "version": 1}
    assert client.put("/api/etat", json={"etat": {"a": 3}, "version": 1}).status_code == 200


# ---------- Dates de péremption ----------
def test_resume_placard_peremption_et_idee():
    from datetime import date
    import placard
    etat = {"pantry": [{"id": "oeuf", "label": "Œufs"}, {"id": "beurre", "label": "Beurre"},
                       {"id": "champignon", "label": "Champignons", "dlc": "2026-11-11"},
                       {"id": "yaourt", "label": "Yaourts", "dlc": "2026-11-08"},
                       {"id": "lait", "label": "Lait", "dlc": "2026-11-30"},
                       {"id": "x:sauce", "label": "Sauce", "dlc": "pas une date"}],
            "courses": [{"id": "pain", "label": "Pain"}]}
    r = placard.resume(etat, date(2026, 11, 10))
    assert r["peremption"] == [{"label": "Yaourts", "dlc": "2026-11-08", "jours": -2},
                               {"label": "Champignons", "dlc": "2026-11-11", "jours": 1}]
    assert r["idee"]["nom"] == "Omelette aux champignons" and r["idee"]["utilise"] == ["Champignons"] and r["idee"]["manque"] == []
    assert r["courses"] == ["Pain"] and r["placard"] == 6
    assert placard.resume({"pantry": [{"id": "oeuf", "label": "Œufs"}]})["idee"] is None  # rien à finir : pas d'idée
    assert placard.jours_restants(None, date(2026, 11, 10)) is None
