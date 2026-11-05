import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import donnees  # noqa: E402
from app import create_app  # noqa: E402
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
    fin = html.index(";</script>", debut)
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
