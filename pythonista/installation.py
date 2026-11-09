"""Installation et mise à jour de l'appli Maison (avec Garde-manger) dans Pythonista.

Ce fichier est lancé par « installer.py » (« Mettre à jour.py » dans le dossier Maison),
qui le télécharge à chaque fois depuis GitHub : il peut donc évoluer sans risque.

Le programme est copié dans le dossier « Maison » d'iCloud (s'il est activé dans Pythonista),
pour que l'iPhone et l'iPad partagent le même placard et la même liste de courses.
« Maison.py » et « Mettre à jour.py » ne sont réécrits que s'ils ont changé, ce qui n'arrive presque jamais :
on peut donc les laisser ouverts dans l'éditeur.
"""

import io
import json
import os
import shutil
import ssl
import sys
import tempfile
import urllib.request
import zipfile

DEPOT = "2kg6nzwjf2-alt/Domotique-Home-Lab"
BRANCHE = "main"
DOSSIERS = ("garde-manger", "maison")
# Bibliothèques en Python pur, pour lire l'adresse iCal de Google (versions compatibles avec Python 3.10)
PAQUETS = [
    ("icalendar", "6.3.2"),
    ("recurring-ical-events", "3.8.2"),
    ("x-wr-timezone", "2.0.1"),
    ("python-dateutil", "2.9.0.post0"),
    ("six", "1.17.0"),
    ("tzdata", "2026.6"),
    ("click", "8.5.0"),
]


def telecharger(url):
    requete = urllib.request.Request(url, headers={"User-Agent": "Maison-installer"})
    with urllib.request.urlopen(requete, timeout=60, context=ssl.create_default_context()) as r:
        return r.read()


# Le dossier iCloud de Pythonista n'est pas dans le dossier privé de l'app (~) mais ici :
CHEMINS_ICLOUD = (
    "/private/var/mobile/Library/Mobile Documents/iCloud~com~omz-software~Pythonista3/Documents",
    "/var/mobile/Library/Mobile Documents/iCloud~com~omz-software~Pythonista3/Documents",
    os.path.expanduser("~/Library/Mobile Documents/iCloud~com~omz-software~Pythonista3/Documents"),
)


def dossier_icloud():
    """Dossier « iCloud » de Pythonista, ou None si iCloud Drive n'est pas activé pour Pythonista."""
    try:  # on le demande à iOS
        from objc_util import ObjCClass
        url = ObjCClass("NSFileManager").defaultManager().URLForUbiquityContainerIdentifier_(None)
        if url:
            chemin = os.path.join(str(url.path()), "Documents")
            os.makedirs(chemin, exist_ok=True)
            return chemin
    except Exception:
        pass
    return next((c for c in CHEMINS_ICLOUD if os.path.isdir(c)), None)


def dossier_cible():
    """Renvoie (dossier Maison, dans iCloud ?, ancien dossier Maison sur l'appareil ou None)."""
    documents = os.path.expanduser("~/Documents")
    if os.environ.get("MAISON_INSTALLER_BASE"):  # essais sur un ordinateur
        return os.path.join(os.environ["MAISON_INSTALLER_BASE"], "Maison"), False, None
    icloud = dossier_icloud()
    local = os.path.join(documents, "Maison")
    if icloud is None:
        return local, False, None
    return os.path.join(icloud, "Maison"), True, (local if os.path.isdir(local) else None)


def migrer_donnees(ancien, cible):
    """Copie les données d'un dossier Maison resté sur l'appareil vers celui d'iCloud.

    Rien n'est copié si iCloud a déjà des données (installées depuis l'autre appareil) :
    on ne remplace jamais le placard ou le ménage déjà partagés.
    """
    source, destination = os.path.join(ancien, "donnees"), os.path.join(cible, "donnees")
    if not os.path.isdir(source):
        return False
    deja = [os.path.join(destination, "menage.json"), os.path.join(destination, "garde-manger", "etat.json")]
    if any(os.path.exists(c) or os.path.exists(os.path.join(os.path.dirname(c), "." + os.path.basename(c) + ".icloud"))
           for c in deja):
        return False
    shutil.copytree(source, destination, dirs_exist_ok=True)
    return True


def copier_si_change(source, destination):
    """Remplace `destination` d'un coup, et seulement si son contenu change. Renvoie True s'il a été réécrit."""
    with open(source, "rb") as f:
        nouveau = f.read()
    try:
        with open(destination, "rb") as f:
            if f.read() == nouveau:
                return False
    except OSError:
        pass
    temporaire = destination + ".nouveau"
    with open(temporaire, "wb") as f:
        f.write(nouveau)
    os.replace(temporaire, destination)
    return True


IGNORES = {"tests", "__pycache__", "donnees_utilisateur"}


def synchroniser_dossier(source, destination):
    """Met `destination` à l'image de `source` fichier par fichier.

    On ne supprime pas le dossier entier pour le recréer : dans iCloud, cela peut faire
    disparaître des fichiers sur l'autre appareil, ou les laisser pas téléchargés.
    Seuls les fichiers modifiés sont réécrits ; ceux qui ne font plus partie du programme sont supprimés.
    """
    attendus = set()
    for racine, sous_dossiers, fichiers in os.walk(source):
        sous_dossiers[:] = [d for d in sous_dossiers if d not in IGNORES]
        cible = os.path.normpath(os.path.join(destination, os.path.relpath(racine, source)))
        os.makedirs(cible, exist_ok=True)
        for nom in fichiers:
            attendus.add(os.path.join(cible, nom))
            copier_si_change(os.path.join(racine, nom), os.path.join(cible, nom))
    for racine, sous_dossiers, fichiers in os.walk(destination):
        sous_dossiers[:] = [d for d in sous_dossiers if d not in IGNORES]
        for nom in fichiers:
            chemin = os.path.normpath(os.path.join(racine, nom))
            if chemin not in attendus and not nom.startswith("."):  # « .x.icloud » : géré par iOS
                os.remove(chemin)


def installer_programme(cible, contenu=None):
    """Renvoie la liste des fichiers de lancement réécrits."""
    if contenu is None:
        print("Téléchargement du programme depuis GitHub…")
        contenu = telecharger(f"https://github.com/{DEPOT}/archive/refs/heads/{BRANCHE}.zip")
    archive = zipfile.ZipFile(io.BytesIO(contenu))
    racine = archive.namelist()[0].split("/")[0]
    os.makedirs(cible, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporaire:
        archive.extractall(temporaire)
        source = os.path.join(temporaire, racine)
        for dossier in DOSSIERS:
            synchroniser_dossier(os.path.join(source, dossier), os.path.join(cible, dossier))
        reecrits = [nom for fichier, nom in (("lancer.py", "Maison.py"), ("installer.py", "Mettre à jour.py"))
                    if copier_si_change(os.path.join(source, "pythonista", fichier), os.path.join(cible, nom))]
    os.makedirs(os.path.join(cible, "donnees"), exist_ok=True)
    return reecrits


def installer_bibliotheques():
    site = os.environ.get("MAISON_INSTALLER_SITE") or os.path.expanduser("~/Documents/site-packages-3")
    os.makedirs(site, exist_ok=True)
    for nom, version in PAQUETS:
        print(f"Bibliothèque {nom} {version}…")
        infos = json.loads(telecharger(f"https://pypi.org/pypi/{nom}/{version}/json"))
        roue = next(u for u in infos["urls"] if u["packagetype"] == "bdist_wheel" and u["filename"].endswith("-none-any.whl"))
        with zipfile.ZipFile(io.BytesIO(telecharger(roue["url"]))) as z:
            fichiers = [e for e in z.namelist() if not e.split("/")[0].endswith(".dist-info")]
            for haut in {e.split("/")[0] for e in fichiers if "/" in e}:  # ancienne version remplacée
                shutil.rmtree(os.path.join(site, haut), ignore_errors=True)
            z.extractall(site, fichiers)
    if site not in sys.path:
        sys.path.insert(0, site)


def main(contenu=None):
    cible, icloud, ancien = dossier_cible()
    reecrits = installer_programme(cible, contenu)
    migre = migrer_donnees(ancien, cible) if ancien else False
    installer_bibliotheques()
    print()
    print("C'est installé dans :", cible)
    if icloud:
        print("Dossier iCloud : le placard et le ménage sont partagés entre l'iPhone et l'iPad.")
    if migre:
        print("Vos données de l'ancien dossier Maison (sur cet appareil) ont été copiées dans iCloud.")
    if ancien:
        print("L'ancien dossier Maison sous « This iPhone / This iPad » ne sert plus : vous pouvez le supprimer.")
        print("Désormais, ouvrez Maison.py et Mettre à jour.py depuis le dossier Maison de la section iCloud.")
    if not icloud:
        print("Attention : iCloud Drive n'est pas activé pour Pythonista, l'iPad n'aura pas les mêmes données.")
        print("Réglages de l'appareil > votre nom > iCloud > iCloud Drive : activez Pythonista, puis relancez ce programme.")
    print("Pour ouvrir l'appli : dossier « Maison », fichier « Maison.py », puis ▶.")
    print("Sur l'autre appareil, lancez une fois « Mettre à jour.py » depuis le dossier Maison.")
    if reecrits:
        print("Remplacés :", ", ".join(reecrits), "— s'ils sont ouverts dans l'éditeur, fermez leur onglet sans enregistrer.")


if __name__ == "__main__":
    main(globals().get("ARCHIVE"))
