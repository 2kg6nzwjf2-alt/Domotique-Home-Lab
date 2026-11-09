"""Installe ou met à jour l'appli Maison (avec Garde-manger) dans Pythonista.

1. Copiez tout ce fichier.
2. Dans Pythonista : touchez « + », choisissez « Empty Script », nommez-le « installer », collez, puis touchez ▶.
3. Pour avoir la dernière version plus tard, lancez « Mettre à jour.py » dans le dossier Maison : vos données sont conservées.

Ce fichier ne change jamais : il télécharge le programme depuis GitHub et lance son installation (installation.py).
"""

import io
import ssl
import urllib.request
import zipfile

DEPOT = "2kg6nzwjf2-alt/Domotique-Home-Lab"
BRANCHE = "main"


def installer():
    print("Téléchargement du programme depuis GitHub…")
    requete = urllib.request.Request(f"https://github.com/{DEPOT}/archive/refs/heads/{BRANCHE}.zip",
                                     headers={"User-Agent": "Maison-installer"})
    with urllib.request.urlopen(requete, timeout=60, context=ssl.create_default_context()) as r:
        archive = r.read()
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        racine = z.namelist()[0].split("/")[0]
        code = z.read(f"{racine}/pythonista/installation.py").decode("utf-8")
    exec(compile(code, "installation.py", "exec"), {"__name__": "__main__", "ARCHIVE": archive})


if __name__ == "__main__":
    installer()
