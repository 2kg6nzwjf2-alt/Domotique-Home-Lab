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


def dossier_cible():
    documents = os.path.expanduser("~/Documents")
    icloud = os.path.expanduser("~/Library/Mobile Documents/iCloud~com~omz-software~Pythonista3/Documents")
    base = icloud if os.path.isdir(icloud) else documents
    return os.path.join(os.environ.get("MAISON_INSTALLER_BASE", base), "Maison"), base == icloud


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
            destination = os.path.join(cible, dossier)
            if os.path.isdir(destination):
                shutil.rmtree(destination)
            shutil.copytree(os.path.join(source, dossier), destination,
                            ignore=shutil.ignore_patterns("tests", "__pycache__", "donnees_utilisateur"))
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
    cible, icloud = dossier_cible()
    reecrits = installer_programme(cible, contenu)
    installer_bibliotheques()
    print()
    print("C'est installé dans :", cible)
    if not icloud:
        print("Attention : iCloud n'est pas activé dans Pythonista, l'iPad n'aura pas les mêmes données.")
    print("Pour ouvrir l'appli : dossier « Maison », fichier « Maison.py », puis ▶.")
    print("Sur l'autre appareil, lancez une fois « Mettre à jour.py » depuis le dossier Maison.")
    if reecrits:
        print("Remplacés :", ", ".join(reecrits), "— s'ils sont ouverts dans l'éditeur, fermez leur onglet sans enregistrer.")


if __name__ == "__main__":
    main(globals().get("ARCHIVE"))
