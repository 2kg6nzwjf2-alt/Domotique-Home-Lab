"""Ouvre l'appli Maison dans Pythonista (iPhone ou iPad).

Ce fichier ne change jamais : le programme est dans le dossier « maison » (lancer_pythonista.py).
Pour fermer l'appli : touchez la croix en haut à gauche.
"""

import os
import runpy

ICI = os.path.dirname(os.path.abspath(__file__))
# dossier Maison sur l'iPhone ; sur un ordinateur, racine du dépôt (démonstration dans le navigateur)
for dossier in (ICI, os.path.dirname(ICI)):
    programme = os.path.join(dossier, "maison", "lancer_pythonista.py")
    if os.path.isfile(programme):
        runpy.run_path(programme, run_name="__main__")
        break
else:
    print("Programme introuvable : lancez « Mettre à jour.py » dans le dossier Maison.")
