# Maison

Tableau de bord de la maison, pensé pour l'iPhone et l'iPad :

- **Météo** : aujourd'hui et demain, par [Open-Meteo](https://open-meteo.com) (gratuit, sans clé) ;
- **Aujourd'hui** : les rendez-vous du jour de Google Agenda ;
- **Tâches** : vos Rappels Apple (tâches, courses…), envoyés par un Raccourci de l'iPhone ;
- **Ménage** : le plan de l'appartement, avec les pièces à nettoyer surlignées et les tâches du jour à cocher ; le planning se modifie dans l'appli ;
- **Garde-manger** : la sous-appli de recettes et de courses, à l'adresse `/garde-manger/`.

Le serveur est en Python (Flask). Une seule connexion par mot de passe protège tout, Garde-manger compris.

## Pourquoi un serveur ?

GitHub Pages ne peut pas faire tourner ce tableau de bord : une page publique ne peut garder ni mot de passe ni clé, et elle ne peut pas lire votre agenda. Il faut donc un serveur. Comme toutes les sources sont accessibles par Internet (Raccourci Apple, agenda Google, météo), il peut tourner :

- **chez un hébergeur** (recommandé si vous n'avez pas d'appareil allumé en permanence) : accessible partout, avec HTTPS. Le `Dockerfile` à la racine du dépôt sert à ça. Il faut un **disque persistant** monté sur `/donnees` et un abonnement de quelques euros par mois ;
- **sur un Raspberry Pi ou un ordinateur toujours allumé** chez vous. Hors de la maison, il faut alors un accès sécurisé, par exemple Tailscale (gratuit), pour ouvrir le tableau de bord et pour que le Raccourci envoie vos rappels.

## Installation

```bash
git clone https://github.com/2kg6nzwjf2-alt/Domotique-Home-Lab.git
cd Domotique-Home-Lab/maison
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
MAISON_MOT_DE_PASSE="un-mot-de-passe-solide" python serveur.py
```

Avec Docker, depuis la racine du dépôt :

```bash
docker build -t maison .
docker run -d -p 8000:8000 -v maison-donnees:/donnees --env-file maison.env maison
```

Ouvrez ensuite l'adresse dans Safari, puis **Partager > Sur l'écran d'accueil**.

## Réglages (variables d'environnement)

| Variable | Rôle |
| --- | --- |
| `MAISON_MOT_DE_PASSE` | Obligatoire : le tableau de bord montre votre agenda et vos tâches. |
| `MAISON_HTTPS` | `1` derrière un hébergeur en HTTPS : cookie sécurisé et adresses correctes. |
| `MAISON_VILLE` | Ville pour la météo, par exemple `Lyon`. |
| `MAISON_AGENDA_ICAL` | Adresse(s) iCal secrète(s) de Google Agenda, séparées par des espaces. |
| `MAISON_CLE_RACCOURCI` | Clé du Raccourci des rappels. Sans elle, une clé est créée et affichée dans les Réglages du tableau de bord. |
| `MAISON_FUSEAU` | Fuseau horaire, `Europe/Paris` par défaut. |
| `MAISON_DONNEES` | Dossier des données (rappels, Garde-manger, clés). |
| `ANTHROPIC_API_KEY` | Facultatif : active les fonctions Claude de Garde-manger. |
| `PORT` | Port d'écoute, 8000 par défaut. |

## Relier Google Agenda

1. Sur un ordinateur, ouvrez Google Agenda, puis **Paramètres**.
2. Choisissez votre agenda à gauche, puis **Intégrer l'agenda**.
3. Copiez l'**Adresse secrète au format iCal** dans `MAISON_AGENDA_ICAL`. Pour plusieurs agendas, mettez plusieurs adresses séparées par des espaces.

Cette adresse donne accès à votre agenda à quiconque la connaît : ne la partagez pas. Google permet de la réinitialiser au même endroit.

## Relier les Rappels Apple (Raccourci)

Apple ne permet à aucun service extérieur de lire les Rappels. Un Raccourci de l'iPhone envoie donc vos rappels non terminés au tableau de bord. L'adresse et la clé à utiliser sont dans **Réglages et Raccourci des rappels**, en bas du tableau de bord.

1. Dans l'appli **Raccourcis**, créez un raccourci nommé « Envoyer mes rappels ».
2. Ajoutez l'action **Rechercher des rappels**, avec le filtre *N'est pas terminé*.
3. Ajoutez **Répéter avec chaque élément**. Dedans, ajoutez une action **Texte** qui contient `Liste | Titre | Date d'échéance`. Remplacez chaque mot par la variable de l'élément répété, en choisissant le format de date *ISO 8601*.
4. Après la boucle, ajoutez **Combiner le texte** avec *Nouvelles lignes*.
5. Ajoutez **Obtenir le contenu de l'URL** :
   - l'adresse affichée dans les Réglages ;
   - méthode **POST** ;
   - en-tête `X-Cle` égal à la clé affichée ;
   - corps **Formulaire**, avec un champ `texte` égal au texte combiné.
6. Dans l'onglet **Automatisation**, lancez ce raccourci quand l'appli **Rappels** est fermée, et chaque matin. Choisissez **Exécuter immédiatement**.

Le bouton **Synchroniser** du tableau de bord lance aussi ce raccourci. Chaque envoi remplace le précédent : un rappel coché dans Rappels disparaît au prochain envoi.

## Tests

```bash
pip install pytest
python -m pytest tests
```

Les tests utilisent de faux agendas, rappels et appareils : aucun compte n'est nécessaire.
