# Maison dans Pythonista (iPhone et iPad, sans serveur)

L'appli Maison (tableau de bord et Garde-manger) tourne directement sur l'iPhone ou l'iPad, dans l'appli [Pythonista](https://apps.apple.com/app/pythonista-3/id1085978097). Aucun serveur ni abonnement n'est nécessaire.

| Fonction | Dans Pythonista |
| --- | --- |
| Tâches (Rappels Apple) | lues directement ; touchez le rond pour cocher une tâche |
| Météo | aujourd'hui et demain pour votre ville ; touchez la carte pour les 7 jours, heure par heure (Open-Meteo, gratuit, sans compte) |
| Agenda du jour | calendrier de l'iPhone (ajoutez-y votre compte Google), ou adresse iCal de Google ; touchez la carte pour les 7 prochains jours |
| Ménage | plan de l'appartement, pièces à nettoyer surlignées, tâches du jour à cocher, planning modifiable ; partagé par iCloud |
| Garde-manger | hors connexion ; placard et courses partagés par iCloud entre l'iPhone et l'iPad |
| Codes-barres | dans Garde-manger, **Scanner un code-barres** prend une photo du code et range le produit au placard (fiche Open Food Facts) |
| Courses | les ingrédients manquants d'une recette sont ajoutés à votre liste Rappels « Courses » |
| Ce soir | Garde-manger propose une recette rapide si la soirée est chargée, et rien si vous dînez dehors |

## Installation (une seule fois)

1. Dans l'app **Réglages** de l'iPhone : touchez votre nom > **iCloud** > **iCloud Drive**, et vérifiez que **Pythonista** est activé dans la liste des apps qui utilisent iCloud Drive (selon la version d'iOS, la liste est sous « Apps synchronisées avec iCloud Drive » ou « Tout afficher »). Dans Pythonista, une section **iCloud** apparaît alors dans la liste des fichiers.
2. Ouvrez [installer.py sur GitHub](https://github.com/2kg6nzwjf2-alt/Domotique-Home-Lab/blob/main/pythonista/installer.py), touchez **Raw**, puis copiez tout le texte.
3. Dans Pythonista, touchez **+**, puis **Empty Script**, nommez-le `installer`, collez le texte et touchez **▶**.
4. Quand le message « C'est installé » apparaît, ouvrez le dossier **Maison** (dans iCloud), puis **Maison.py**, et touchez **▶**.
5. Au premier lancement, autorisez Pythonista à accéder aux **Rappels** et au **Calendrier**, puis à l'**appareil photo** au premier scan de code-barres.

Sur l'iPad : le dossier Maison arrive par iCloud. Lancez une fois **Mettre à jour.py**, qui installe les bibliothèques sur l'iPad, puis **Maison.py**.

Pour avoir la dernière version plus tard, lancez **Mettre à jour.py** : vos données sont conservées.

**Maison.py** et **Mettre à jour.py** ne changent jamais : ils lancent le programme rangé dans les dossiers `maison` et `garde-manger`, que les mises à jour remplacent. Vous pouvez donc les laisser ouverts dans l'éditeur pendant une mise à jour.

## iPhone et iPad synchronisés

Le placard, les courses, les codes-barres mémorisés et le ménage sont dans le dossier **Maison** d'iCloud Drive : l'iPhone et l'iPad lisent les mêmes fichiers.

- Avant chaque lecture, l'appli demande à iOS la dernière version du fichier ; Garde-manger vérifie toutes les 30 secondes si l'autre appareil a modifié le placard.
- Si les deux appareils modifient le placard en même temps, les changements sont fusionnés : rien n'est écrasé.
- En bas du tableau de bord, **Réglages** indique si les données sont bien dans iCloud, et sur quel appareil et à quelle heure le placard et le ménage ont été modifiés en dernier : les deux appareils doivent afficher les mêmes heures. Le bouton **Synchroniser maintenant** redemande les fichiers à iCloud.
- Si le planning du ménage a été changé sur l'autre appareil pendant que vous le modifiiez, il est rechargé au lieu d'être écrasé.

Si un appareil n'a pas les mêmes données : vérifiez sur cet appareil que **Pythonista** est activé dans Réglages > votre nom > iCloud > iCloud Drive, et que le dossier **Maison** est rangé sous **iCloud** dans la liste des fichiers de Pythonista, pas sous « This iPhone » ou « This iPad ». Sinon, activez Pythonista pour iCloud Drive, supprimez ce dossier Maison local, puis lancez **Mettre à jour.py** depuis le dossier Maison d'iCloud.

## Réglages

En bas du tableau de bord, la section **Réglages** permet de choisir :

- la ville pour la météo ;
- la liste Rappels qui sert de liste de courses (« Courses » par défaut) ;
- l'adresse iCal de Google (facultative : sans elle, l'agenda lit le calendrier de l'iPhone).

Les réglages sont gardés dans le trousseau de l'appareil : saisissez-les une fois sur l'iPhone et une fois sur l'iPad.

Pour voir l'agenda Google sans adresse iCal : sur l'iPhone, **Réglages > Apps > Calendrier > Comptes de calendrier**, ajoutez votre compte Google et activez Calendriers.

## Une icône sur l'écran d'accueil

1. Ouvrez l'appli **Raccourcis**, touchez **+**.
2. Ajoutez l'action **Ouvrir les URL** avec l'adresse : `pythonista3://Maison/Maison.py?action=run&root=icloud`
3. Nommez le raccourci « Maison », puis **Partager > Sur l'écran d'accueil**.

Pour fermer l'appli, touchez la croix en haut à gauche.

## Limites

- L'appli se met à jour seulement quand elle est ouverte : pas de notification quand elle est fermée.
- Les fonctions Claude de Garde-manger (recette d'un plat inconnu, idées, photo du frigo) ne sont pas dans cette version.
- Si Pythonista n'a pas le droit de lire le Calendrier, l'agenda le signale : indiquez alors l'adresse iCal de Google dans les Réglages.

## Essayer sur un ordinateur

`python pythonista/lancer.py` ouvre une démonstration dans le navigateur, avec des Rappels et un agenda simulés.
