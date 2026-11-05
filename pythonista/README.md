# Maison dans Pythonista (iPhone et iPad, sans serveur)

L'appli Maison (tableau de bord et Garde-manger) tourne directement sur l'iPhone ou l'iPad, dans l'appli [Pythonista](https://apps.apple.com/app/pythonista-3/id1085978097). Aucun serveur ni abonnement n'est nécessaire.

| Fonction | Dans Pythonista |
| --- | --- |
| Tâches (Rappels Apple) | lues directement ; touchez le rond pour cocher une tâche |
| Météo | aujourd'hui et demain pour votre ville (Open-Meteo, gratuit, sans compte) |
| Agenda du jour | calendrier de l'iPhone (ajoutez-y votre compte Google), ou adresse iCal de Google |
| Alarme et caméra Smart Life | avec vos clés Tuya, rangées dans le trousseau de l'appareil |
| Garde-manger | hors connexion ; placard et courses partagés par iCloud entre l'iPhone et l'iPad |
| Courses | les ingrédients manquants d'une recette sont ajoutés à votre liste Rappels « Courses » |
| Ce soir | Garde-manger propose une recette rapide si la soirée est chargée, et rien si vous dînez dehors |

## Installation (une seule fois)

1. Dans Pythonista, ouvrez les réglages (roue dentée) et activez **iCloud**.
2. Ouvrez [installer.py sur GitHub](https://github.com/2kg6nzwjf2-alt/Domotique-Home-Lab/blob/main/pythonista/installer.py), touchez **Raw**, puis copiez tout le texte.
3. Dans Pythonista, touchez **+**, puis **Empty Script**, nommez-le `installer`, collez le texte et touchez **▶**.
4. Quand le message « C'est installé » apparaît, ouvrez le dossier **Maison** (dans iCloud), puis **Maison.py**, et touchez **▶**.
5. Au premier lancement, autorisez Pythonista à accéder aux **Rappels** et au **Calendrier**.

Sur l'iPad : le dossier Maison arrive par iCloud. Lancez une fois **Mettre à jour.py**, qui installe les bibliothèques sur l'iPad, puis **Maison.py**.

Pour avoir la dernière version plus tard, lancez **Mettre à jour.py** : vos données sont conservées.

## Réglages

En bas du tableau de bord, la section **Réglages** permet de choisir :

- la ville pour la météo ;
- la liste Rappels qui sert de liste de courses (« Courses » par défaut) ;
- l'adresse iCal de Google (facultative : sans elle, l'agenda lit le calendrier de l'iPhone) ;
- les clés Smart Life (Access ID et Access Secret du projet Tuya) et les identifiants de l'alarme et de la caméra. Les étapes pour les obtenir sont dans le [README de Maison](../maison/README.md#relier-lalarme-et-la-caméra-smart-life).

Les clés sont gardées dans le trousseau de l'appareil : saisissez-les une fois sur l'iPhone et une fois sur l'iPad.

Pour voir l'agenda Google sans adresse iCal : sur l'iPhone, **Réglages > Apps > Calendrier > Comptes de calendrier**, ajoutez votre compte Google et activez Calendriers.

## Une icône sur l'écran d'accueil

1. Ouvrez l'appli **Raccourcis**, touchez **+**.
2. Ajoutez l'action **Ouvrir les URL** avec l'adresse : `pythonista3://Maison/Maison.py?action=run&root=icloud`
3. Nommez le raccourci « Maison », puis **Partager > Sur l'écran d'accueil**.

Pour fermer l'appli, touchez la croix en haut à gauche.

## Limites

- L'appli se met à jour seulement quand elle est ouverte : pas de notification quand elle est fermée (par exemple si l'alarme se déclenche).
- Les fonctions Claude de Garde-manger (recette d'un plat inconnu, idées, photo du frigo) ne sont pas dans cette version.
- Si Pythonista n'a pas le droit de lire le Calendrier, l'agenda le signale : indiquez alors l'adresse iCal de Google dans les Réglages.

## Essayer sur un ordinateur

`python pythonista/lancer.py` ouvre une démonstration dans le navigateur, avec des Rappels et un agenda simulés.
