"""Programme de l'appli Maison dans Pythonista (iPhone ou iPad), lancé par « Maison.py ».

Pour la fermer : touchez la croix en haut à gauche de la page (ou glissez vers le bas avec deux doigts).
Sur un ordinateur, `python pythonista/lancer.py` lance une version de démonstration dans le navigateur.
"""

import os
import sys
import threading
import time

# Dossier « Maison » sur l'iPhone (racine du dépôt sur un ordinateur)
RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOS_DOSSIERS = [os.path.join(RACINE, d) for d in ("maison", "garde-manger")]


def oublier_anciens_modules():
    """Pythonista garde en mémoire les modules d'un lancement à l'autre.

    Si l'appli a d'abord été lancée depuis un autre dossier Maison (par exemple l'ancien,
    sur l'appareil, avant le passage dans iCloud), ses modules et ses chemins resteraient
    utilisés : on les oublie pour charger ceux de ce dossier-ci.
    """
    def a_nous(chemin):
        return os.path.basename(os.path.normpath(chemin)) in ("maison", "garde-manger")

    sys.path[:] = [c for c in sys.path if not (c and a_nous(c) and os.path.normpath(c) not in NOS_DOSSIERS)]
    for nom, module in list(sys.modules.items()):
        fichier = getattr(module, "__file__", None)
        if nom != "__main__" and fichier and a_nous(os.path.dirname(os.path.abspath(fichier))):
            del sys.modules[nom]  # rechargé depuis ce dossier à l'import suivant
    for chemin in reversed(NOS_DOSSIERS):
        if chemin in sys.path:
            sys.path.remove(chemin)
        sys.path.insert(0, chemin)


oublier_anciens_modules()

try:
    import ui  # présent seulement dans Pythonista
except ImportError:
    ui = None



def fichiers_pas_telecharges(dossiers):
    """Fichiers du programme qu'iCloud n'a pas encore descendus sur l'appareil (« .nom.icloud »)."""
    manquants = []
    for dossier in dossiers:
        for racine, sous_dossiers, fichiers in os.walk(dossier):
            sous_dossiers[:] = [d for d in sous_dossiers if d != "__pycache__"]
            manquants += [os.path.join(racine, f[1:-len(".icloud")]) for f in fichiers
                          if f.startswith(".") and f.endswith(".icloud") and len(f) > 8]
    return [c for c in manquants if not os.path.exists(c)]


def telecharger_programme(attente=45):
    """Demande à iOS les fichiers du programme restés dans iCloud et attend qu'ils arrivent.

    Fait avant tout import du programme : ces fichiers peuvent eux-mêmes manquer.
    Renvoie la liste des fichiers toujours absents.
    """
    dossiers = [os.path.join(RACINE, d) for d in ("maison", "garde-manger")]
    manquants = fichiers_pas_telecharges(dossiers)
    if not manquants or ui is None:
        return manquants
    print(f"Téléchargement de {len(manquants)} fichier(s) du programme depuis iCloud…")
    try:
        from objc_util import ObjCClass
        gestionnaire, URL = ObjCClass("NSFileManager").defaultManager(), ObjCClass("NSURL")
        for chemin in manquants:
            gestionnaire.startDownloadingUbiquitousItemAtURL_error_(URL.fileURLWithPath_(chemin), None)
    except Exception as e:
        print("Demande à iCloud impossible :", e)
    fin = time.time() + attente
    while manquants and time.time() < fin:
        time.sleep(0.5)
        manquants = [c for c in manquants if not os.path.exists(c)]
    return manquants


MANQUANTS = telecharger_programme()
if MANQUANTS:
    print("Ces fichiers ne sont pas encore arrivés d'iCloud :")
    for chemin in MANQUANTS[:8]:
        print(" -", os.path.relpath(chemin, RACINE))
    print("Vérifiez la connexion Internet, attendez un peu et relancez Maison.py.")
    print("Si ça continue, lancez « Mettre à jour.py » : il réinstalle le programme.")
    raise SystemExit(1)

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


def sans_rebond(vue):
    """Coupe l'effet élastique de la page : sur iPad, tirer au-delà du bord faisait bouger tout le contenu, fenêtres comprises."""
    try:
        from objc_util import ObjCClass, ObjCInstance, on_main_thread
    except ImportError:
        return

    @on_main_thread
    def appliquer():
        defilantes = ObjCClass("UIScrollView")
        pile = [ObjCInstance(vue)]
        while pile:
            v = pile.pop()
            if v.isKindOfClass_(defilantes):
                v.setBounces_(False)
            pile.extend(list(v.subviews() or []))

    try:
        appliquer()
    except Exception as e:
        print("Effet élastique non désactivé :", e)


def hauteur_barre_etat():
    """Hauteur de la barre d'état (heure, batterie), que la page laisse libre sans barre de titre."""
    try:
        from objc_util import ObjCClass, on_main_thread

        @on_main_thread
        def mesurer():
            fenetres = ObjCClass("UIApplication").sharedApplication().windows()
            hauteurs = [float(f.safeAreaInsets().top) for f in fenetres] if fenetres else []
            return max(hauteurs + [float(ObjCClass("UIApplication").sharedApplication().statusBarFrame().size.height)])
        return int(round(mesurer()))
    except Exception as e:
        print("Hauteur de la barre d'état inconnue :", e)
        return 20


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
        try:
            icloud = plateforme.ICloudIOS()
        except Exception as e:
            print("Téléchargement iCloud indisponible :", e)
            icloud = None
        try:
            ecran = plateforme.EcranIOS()
        except Exception as e:
            print("Mode cadre : écran toujours allumé indisponible :", e)
            ecran = None
    else:
        rappels = plateforme.RappelsSimules(os.path.join(DONNEES, "rappels-demo.json"))
        agenda = plateforme.AgendaSimule()
        coffre = plateforme.CoffreFichier(os.path.join(DONNEES, "reglages-demo.json"))
        scanner = icloud = ecran = None
    # données partagées entre l'iPhone et l'iPad seulement si le dossier Maison est dans iCloud Drive
    partage = "icloud" if "Mobile Documents" in os.path.abspath(DONNEES) else "appareil"
    return appli_locale.Appli(DONNEES, rappels, agenda, coffre, scanner=scanner,
                              icloud=icloud, appareil=plateforme.nom_appareil(), partage=partage, ecran=ecran)


def main():
    appli = creer_appli()
    serveur, adresse = appli_locale.demarrer(appli)
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
    # Pas de barre de titre de Pythonista (bandeau blanc, même la nuit) : la page a sa propre croix,
    # qui appelle appli.fermer (glisser vers le bas avec deux doigts ferme aussi la fenêtre).
    # Croix et hauteur de la barre d'état sont prêtes avant le chargement de la page, qui les utilise.
    def fermer():
        fenetre.close()
        fini.set()
    appli.fermer = lambda: ui.delay(fermer, 0.1)
    appli.marge_haut = hauteur_barre_etat()
    vue.load_url(adresse)
    fenetre.present("fullscreen", hide_title_bar=True)
    sans_rebond(vue)
    try:
        while not fini.wait(0.5):
            pass
    finally:
        serveur.shutdown()
        if appli.ecran is not None:  # mode cadre : l'écran peut de nouveau se mettre en veille
            try:
                appli.ecran.garder_allume(False)
            except Exception:
                pass


if __name__ == "__main__":
    main()
