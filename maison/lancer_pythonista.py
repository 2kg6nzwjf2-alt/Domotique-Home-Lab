"""Programme de l'appli Maison dans Pythonista (iPhone ou iPad), lancé par « Maison.py ».

Pour la fermer : touchez la croix en haut à gauche.
Sur un ordinateur, `python pythonista/lancer.py` lance une version de démonstration dans le navigateur.
"""

import os
import sys
import threading

# Dossier « Maison » sur l'iPhone (racine du dépôt sur un ordinateur)
RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for dossier in ("maison", "garde-manger"):
    chemin = os.path.join(RACINE, dossier)
    if chemin not in sys.path:
        sys.path.insert(0, chemin)

try:
    import ui  # présent seulement dans Pythonista
except ImportError:
    ui = None

import appli_locale  # noqa: E402
import plateforme  # noqa: E402

DONNEES = os.path.join(RACINE, "donnees")

if ui is not None:
    class Fenetre(ui.View):
        """Fenêtre de l'appli : prévient quand on la ferme."""

        fini = None

        def will_close(self):
            if self.fini is not None:
                self.fini.set()


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
    # Le serveur s'arrête seulement quand la fenêtre est fermée par la croix (will_close).
    # wait_modal() ne convient pas : il rend la main dès qu'une autre vue recouvre la fenêtre,
    # par exemple l'appareil photo du scan des codes-barres, et le serveur s'arrêtait alors.
    fini = threading.Event()
    fenetre = Fenetre(name="Maison", background_color="#f3f5f9")
    fenetre.fini = fini
    vue = ui.WebView(frame=fenetre.bounds, flex="WH")
    vue.background_color = "#f3f5f9"
    fenetre.add_subview(vue)
    vue.load_url(adresse)
    fenetre.present("fullscreen")
    try:
        while not fini.wait(0.5):
            pass
    finally:
        serveur.shutdown()


if __name__ == "__main__":
    main()
