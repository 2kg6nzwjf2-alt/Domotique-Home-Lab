"""Ouvre l'appli Maison dans Pythonista (iPhone ou iPad).

Pour la fermer : touchez la croix en haut à gauche.
Sur un ordinateur, ce fichier lance une version de démonstration dans le navigateur.
"""

import os
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
for dossier in ("maison", "garde-manger"):
    chemin = os.path.join(ICI, dossier)
    if chemin not in sys.path:
        sys.path.insert(0, chemin)

try:
    import ui  # présent seulement dans Pythonista
except ImportError:
    ui = None

import appli_locale  # noqa: E402
import plateforme  # noqa: E402

DONNEES = os.path.join(ICI, "donnees")


def creer_appli():
    if ui is not None:
        try:
            rappels = plateforme.RappelsIOS()
        except Exception as e:
            print("Rappels indisponibles :", e)
            rappels = plateforme.RappelsSimules(os.path.join(DONNEES, "rappels-demo.json"))
        try:
            agenda = plateforme.AgendaIOS()
        except Exception as e:
            print("Calendrier indisponible :", e)
            agenda = None
        coffre = plateforme.CoffreIOS()
        try:
            scanner = plateforme.ScannerIOS()
        except Exception as e:
            print("Scan des codes-barres indisponible :", e)
            scanner = None
    else:
        rappels = plateforme.RappelsSimules(os.path.join(DONNEES, "rappels-demo.json"))
        agenda = plateforme.AgendaSimule()
        coffre = plateforme.CoffreFichier(os.path.join(DONNEES, "reglages-demo.json"))
        scanner = None
    return appli_locale.Appli(DONNEES, rappels, agenda, coffre, scanner=scanner)


def main():
    serveur, adresse = appli_locale.demarrer(creer_appli())
    if ui is None:
        print("Démonstration ouverte sur", adresse, "(Ctrl+C pour arrêter)")
        import webbrowser
        webbrowser.open(adresse)
        import time
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            serveur.shutdown()
        return
    vue = ui.WebView(name="Maison")
    vue.background_color = "#f3f5f9"
    vue.load_url(adresse)
    vue.present("fullscreen")
    vue.wait_modal()
    serveur.shutdown()


if __name__ == "__main__":
    main()
