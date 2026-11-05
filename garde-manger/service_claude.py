"""Recettes, idées et photo du frigo avec Claude (facultatif).

Activé seulement si une clé API Anthropic est configurée
(variable d'environnement ANTHROPIC_API_KEY). Sans clé, l'appli
fonctionne normalement avec son carnet de recettes.
"""

import base64
import json
import os
import re

import anthropic

MODELE = os.environ.get("GM_MODELE", "claude-opus-5-5")
EFFORT = os.environ.get("GM_EFFORT", "medium")
TYPES_IMAGE = {"image/jpeg", "image/png", "image/webp", "image/gif"}


class ErreurClaude(Exception):
    """Erreur à renvoyer à l'interface : `code` est lu par le JavaScript."""

    def __init__(self, code, message, statut=502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.statut = statut


def lire_json(texte):
    """Lit la réponse de Claude comme du JSON, même entourée d'une phrase ou d'un bloc ```."""
    texte = texte.strip()
    try:
        return json.loads(texte)
    except ValueError:
        pass
    bloc = re.search(r"```(?:json)?\s*(.*?)```", texte, re.S)
    if bloc:
        try:
            return json.loads(bloc.group(1))
        except ValueError:
            pass
    debuts = [i for i in (texte.find("{"), texte.find("[")) if i >= 0]
    if debuts:
        debut = min(debuts)
        fin = max(texte.rfind("}"), texte.rfind("]"))
        if fin > debut:
            try:
                return json.loads(texte[debut : fin + 1])
            except ValueError:
                pass
    raise ErreurClaude("invalid_json", "réponse illisible")


def _personnes(n):
    return f"{n} personne{'s' if n > 1 else ''}"


def _liste(valeurs, defaut="aucun"):
    return ", ".join(valeurs) if valeurs else defaut


def consigne_plat(nom, personnes, ustensiles):
    p = _personnes(personnes)
    return f"""Recette demandée : « {nom} », pour {p}.
Donne la recette la plus classique en France pour ce plat.
Réponds uniquement avec un objet JSON, sans aucun autre texte :
{{"nom":"Nom du plat","minutes":45,"preparation":15,"cuisson":30,"repos":0,"difficulte":"Facile","portions":{personnes},"ingredients":[{{"nom":"lardons","quantite":"200 g","facultatif":false}}],"ustensiles":["poêle","saladier"],"etapes":["..."]}}
Règles :
- "nom" d'un ingrédient : le nom simple de l'aliment en français, sans quantité ni découpe (ex. "oignon", "crème fraîche", "pommes de terre").
- "quantite" : quantité pour {p}, un nombre puis éventuellement une unité parmi g, kg, cl, L, c. à s., c. à c., tranche, gousse, boîte, rouleau, sachet (ex. "200 g", "3", "2 c. à s."). Rien d'autre.
- N'inclus pas sel, poivre, huile ni eau.
- "ustensiles" : les ustensiles nécessaires, sans couteau, planche ni cuillères. Mes ustensiles : {_liste(ustensiles)}. Si le plat en demande un autre, garde-le dans la liste.
- "preparation", "cuisson" et "repos" en minutes ; "minutes" = preparation + cuisson (sans le repos) ; "difficulte" vaut "Facile", "Moyen" ou "Difficile" pour un cuisinier amateur.
- 4 à 8 étapes courtes et concrètes, avec les durées en minutes quand il y en a (ex. "Laissez mijoter 20 min.").
Si « {nom} » n'est pas un plat ou un dessert qu'on peut cuisiner, réponds {{"erreur":"une phrase courte en français"}}."""


def consigne_idees(placard, personnes, ustensiles, filtres, deja):
    produits = []
    for item in placard:
        texte = item["nom"]
        if item.get("quantite"):
            texte += f" ({item['quantite']})"
        produits.append(texte)
    a_finir = [item["nom"] for item in placard if item.get("a_finir")]
    contraintes = []
    if filtres.get("vegetarien"):
        contraintes.append("végétarien")
    if filtres.get("rapide"):
        contraintes.append("30 minutes maximum")
    if filtres.get("facile"):
        contraintes.append("recettes faciles uniquement")
    contraintes.append({
        "dessert": "uniquement des desserts",
        "plat": "des plats principaux",
        "entree": "des entrées ou des soupes",
    }.get(filtres.get("type"), ""))
    contraintes = [c for c in contraintes if c]
    p = _personnes(personnes)
    lignes = [
        "Tu es un cuisinier familial français, inventif et pratique.",
        f"Ingrédients disponibles chez moi (quantité entre parenthèses quand je la connais) : {_liste(produits)}.",
        f"Nous sommes {p} : donne les quantités pour {p}.",
        f"Mes ustensiles : {_liste(ustensiles)} (plus couteaux, planche, cuillères). N'utilise que ceux-là.",
    ]
    if a_finir:
        lignes.append(f"À utiliser en priorité car ils vont se perdre : {', '.join(a_finir)}.")
    lignes.append("Toujours disponibles : sel, poivre, huile, eau.")
    if contraintes:
        lignes.append(f"Contraintes : {' ; '.join(contraintes)}.")
    if deja:
        lignes.append(f"Ne propose pas ces plats déjà suggérés : {', '.join(deja)}.")
    lignes += [
        "Propose 4 plats variés, réalisables surtout avec mes ingrédients et mes quantités. Au plus 2 ingrédients à acheter par plat, idéalement aucun. Quantités précises (g, cl, nombre), étapes courtes et concrètes (4 à 6), en français.",
        "Réponds uniquement avec un objet JSON, sans aucun autre texte :",
        f'{{"recettes":[{{"nom":"...","minutes":25,"preparation":10,"cuisson":15,"repos":0,"difficulte":"Facile","portions":{personnes},"pourquoi":"une phrase courte","ingredients":[{{"nom":"...","quantite":"...","dispo":true,"facultatif":false}}],"ustensiles":["..."],"etapes":["..."]}}]}}',
        '"minutes" = preparation + cuisson ; "difficulte" vaut "Facile", "Moyen" ou "Difficile".',
        '"dispo" vaut true si j\'ai l\'ingrédient en quantité suffisante (quand je n\'ai pas précisé de quantité, considère que j\'en ai assez) ou si c\'est un basique toujours disponible, sinon false. Si j\'en ai mais pas assez, mets dispo false et indique dans "quantite" ce qu\'il faut au total et ce qui manque, par exemple "6 (il en manque 2)".',
    ]
    return "\n".join(lignes)


CONSIGNE_PHOTO = (
    "Cette photo montre l'intérieur d'un frigo, d'un placard ou des courses. "
    "Liste les ingrédients alimentaires que tu identifies avec certitude, en français, "
    "au singulier ou pluriel usuel, sans marque ni quantité (ex. \"œufs\", \"lait\", \"courgette\"). "
    "Réponds uniquement avec un tableau JSON de chaînes, par exemple [\"œufs\",\"lait\",\"beurre\"]. "
    "Si tu ne vois aucun aliment, réponds []."
)


class ServiceClaude:
    def __init__(self, client=None):
        self.client = client or anthropic.Anthropic()

    @classmethod
    def depuis_environnement(cls):
        if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            return None
        return cls()

    def appeler(self, contenu):
        """Envoie un message à Claude et renvoie le texte de la réponse."""
        try:
            reponse = self.client.beta.messages.create(
                model=MODELE,
                max_tokens=16000,
                output_config={"effort": EFFORT},
                # Si Claude refuse pour raison de sécurité, l'API réessaie avec le modèle recommandé.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[{"role": "user", "content": contenu}],
            )
        except anthropic.AuthenticationError:
            raise ErreurClaude("config", "clé API Anthropic refusée", 500)
        except anthropic.PermissionDeniedError:
            raise ErreurClaude("config", "la clé API n'a pas accès à ce modèle", 500)
        except anthropic.RateLimitError:
            raise ErreurClaude("rate_limited", "trop de demandes", 429)
        except anthropic.APIConnectionError:
            raise ErreurClaude("upstream_error", "Claude injoignable", 502)
        except anthropic.APIStatusError as e:
            raise ErreurClaude("upstream_error", f"erreur {e.status_code} de l'API", 502)
        if reponse.stop_reason == "refusal":
            raise ErreurClaude("refused", "demande refusée", 422)
        texte = "".join(b.text for b in reponse.content if b.type == "text")
        if not texte.strip():
            raise ErreurClaude("invalid_json", "réponse vide")
        return texte

    def recette(self, nom, personnes, ustensiles):
        resultat = lire_json(self.appeler(consigne_plat(nom, personnes, ustensiles)))
        if not isinstance(resultat, dict):
            raise ErreurClaude("invalid_json", "réponse inattendue")
        return resultat

    def idees(self, placard, personnes, ustensiles, filtres, deja):
        resultat = lire_json(self.appeler(consigne_idees(placard, personnes, ustensiles, filtres, deja)))
        recettes = resultat.get("recettes") if isinstance(resultat, dict) else resultat
        if not isinstance(recettes, list):
            raise ErreurClaude("invalid_json", "réponse inattendue")
        return [r for r in recettes if isinstance(r, dict)]

    def produits_sur_photo(self, image, type_image):
        if type_image not in TYPES_IMAGE:
            raise ErreurClaude("image_rejected", "format d'image non pris en charge", 400)
        contenu = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": type_image, "data": base64.standard_b64encode(image).decode("ascii")},
            },
            {"type": "text", "text": CONSIGNE_PHOTO},
        ]
        resultat = lire_json(self.appeler(contenu))
        if not isinstance(resultat, list):
            raise ErreurClaude("invalid_json", "réponse inattendue")
        return [str(x) for x in resultat if isinstance(x, (str, int, float))][:40]
