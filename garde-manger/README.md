# Garde-manger

Notez ce que vous avez dans vos placards : l'appli propose les plats que vous pouvez cuisiner, avec les quantités, la difficulté et le temps. Elle vous guide ensuite pas à pas avec des minuteurs et prépare la liste de courses.

Le serveur et les données sont en **Python** (Flask). L'interface s'ouvre dans Safari sur **iPhone et iPad**, et s'installe sur l'écran d'accueil comme une appli. Le placard, les ustensiles et la liste de courses sont gardés par le serveur : l'iPhone et l'iPad voient les mêmes.

## Ce qu'il faut

- Un ordinateur (Mac, Windows ou Linux) ou un Raspberry Pi, avec **Python 3.10 ou plus récent**, allumé quand vous voulez utiliser l'appli.
- L'iPhone ou l'iPad connecté au **même réseau Wi-Fi** que cet ordinateur.

## Installation

```bash
git clone https://github.com/2kg6nzwjf2-alt/Domotique-Home-Lab.git
cd Domotique-Home-Lab/garde-manger
python3 -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Le terminal affiche l'adresse à ouvrir, par exemple `http://192.168.1.20:5000`.

## Sur l'iPhone et l'iPad

1. Ouvrez l'adresse affichée dans **Safari**.
2. Touchez **Partager**, puis **Sur l'écran d'accueil**.
3. L'icône Garde-manger s'ouvre ensuite en plein écran, comme une appli.

Si la page ne s'ouvre pas, vérifiez que l'ordinateur est allumé, que `python app.py` tourne et que le téléphone est sur le même Wi-Fi. Le pare-feu de l'ordinateur doit autoriser les connexions entrantes sur le port 5000.

## Réglages (variables d'environnement)

| Variable | Rôle | Par défaut |
| --- | --- | --- |
| `GM_MOT_DE_PASSE` | Demande un mot de passe à l'ouverture. Indispensable si l'appli est accessible hors de chez vous. | aucun |
| `ANTHROPIC_API_KEY` | Active les fonctions Claude (voir plus bas). | aucune |
| `GM_MODELE` | Modèle Claude utilisé. | `claude-opus-5-5` |
| `GM_EFFORT` | Effort de réflexion de Claude : `low`, `medium` ou `high`. | `medium` |
| `GM_DOSSIER_DONNEES` | Dossier où le placard est enregistré (`etat.json`). | `donnees_utilisateur/` |
| `GM_PORT` ou `PORT` | Port du serveur. | `5000` |
| `GM_HOTE` | Adresse d'écoute. `127.0.0.1` limite l'accès à l'ordinateur lui-même. | `0.0.0.0` |

Exemple :

```bash
GM_MOT_DE_PASSE="mon-mot-de-passe" ANTHROPIC_API_KEY="sk-ant-..." python app.py
```

Sans mot de passe, toute personne connectée à votre Wi-Fi peut ouvrir l'appli. C'est acceptable à la maison, pas sur un réseau public.

## Fonctions Claude (facultatives)

Avec une clé API Anthropic (créée sur [platform.claude.com](https://platform.claude.com)), trois fonctions s'ajoutent :

- **Recette par Claude** : la recette de n'importe quel plat tapé dans « Un plat en tête ? ».
- **Idées sur mesure** : 4 plats inventés à partir de votre placard, de vos quantités et de vos ustensiles.
- **Photo du frigo** : Claude repère les aliments sur une photo et les ajoute au placard.

Chaque demande est facturée sur votre compte API Anthropic. Sans clé, ces fonctions sont simplement masquées. Le reste de l'appli fonctionne normalement : le carnet de 45 recettes, les quantités, les ustensiles, le pas à pas, les minuteurs et la liste de courses.

## Carrefour et E.Leclerc

Ni Carrefour ni E.Leclerc ne proposent d'API publique pour les particuliers. Le connecteur Carrefour de claude.ai ne fonctionne qu'à l'intérieur de claude.ai, donc il n'est pas repris ici. La liste de courses reste copiable avec le bouton « Copier ».

## Héberger l'appli hors de chez vous

L'appli peut tourner chez un hébergeur Python. Elle utilise la variable `PORT` quand l'hébergeur la fournit. Deux conditions :

- un **disque persistant** pour `GM_DOSSIER_DONNEES`, sinon le placard est perdu à chaque redémarrage ;
- un **mot de passe** (`GM_MOT_DE_PASSE`), puisque l'adresse sera accessible depuis Internet.

## Organisation du code

| Fichier | Contenu |
| --- | --- |
| `app.py` | Serveur Flask : pages, connexion, enregistrement du placard, appels à Claude. |
| `donnees.py` | Produits connus et carnet de recettes. Ajoutez vos recettes ici. |
| `service_claude.py` | Consignes envoyées à Claude et lecture de ses réponses. |
| `stockage.py` | Enregistrement de l'état dans un fichier JSON. |
| `templates/index.html` | Interface affichée dans Safari. |
| `static/` | Icônes et manifeste pour l'écran d'accueil. |
| `tests/` | Tests automatiques. |

### Ajouter une recette

Ajoutez un dictionnaire à `RECETTES` dans `donnees.py`, sur le modèle des recettes existantes. Chaque ingrédient s'écrit `"clé:quantité"`, avec une clé de `PRODUITS`. Un `?` devant l'ingrédient le rend facultatif. Lancez ensuite les tests, qui vérifient que chaque ingrédient existe :

```bash
pip install -r requirements-dev.txt
python -m pytest
```
