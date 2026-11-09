"""Accès à l'iPhone ou l'iPad depuis Pythonista : Rappels, Calendrier et trousseau.

Chaque source a deux versions :
- « IOS » : utilisée dans Pythonista (modules reminders, keychain et objc_util) ;
- « Simulé » : utilisée sur un ordinateur et dans les tests, avec des fichiers JSON.
"""

import json
import os
import threading
import time
import unicodedata
from datetime import date, datetime, timedelta


def _cle_titre(texte):
    """« Lardons (50 g) » et « lardons » désignent le même article de courses."""
    texte = str(texte or "").split(" (")[0].strip().lower()
    return "".join(c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn")


def _cle_liste(nom):
    """Nom de liste comparé sans tenir compte des majuscules ni des espaces (toutes écritures : 買い物リスト…)."""
    return " ".join(unicodedata.normalize("NFKC", str(nom or "")).casefold().split())


class ListeIntrouvable(ValueError):
    pass


def _rappel(identifiant, liste, titre, echeance):
    journee = False
    if isinstance(echeance, datetime):
        journee = echeance.hour == 0 and echeance.minute == 0
        if echeance.tzinfo is None:
            echeance = echeance.astimezone()
        echeance = echeance.isoformat()
    elif isinstance(echeance, date):  # échéance sans heure
        journee, echeance = True, echeance.isoformat()
    elif echeance is not None and not isinstance(echeance, str):
        echeance = None
    return {"id": identifiant, "liste": str(liste or "Rappels")[:60], "titre": str(titre or "")[:200],
            "echeance": echeance or None, "journee": journee}


# ---------------------------------------------------------------- Rappels

class RappelsIOS:
    """Appli Rappels, par le module `reminders` de Pythonista."""

    def __init__(self):
        import reminders
        self._r = reminders
        self._cache = {}
        self.erreurs = []  # listes qui n'ont pas pu être lues au dernier passage
        self._verrou = threading.Lock()

    def _listes(self):
        return list(self._r.get_all_calendars())

    def listes(self):
        """Toutes les listes vues par Pythonista, avec le nombre de rappels non terminés."""
        resultat = []
        for liste in self._listes():
            try:
                nombre, erreur = len(self._r.get_reminders(calendar=liste, completed=False)), None
            except Exception as e:
                nombre, erreur = None, type(e).__name__
            resultat.append({"nom": str(liste.title), "nombre": nombre, "erreur": erreur})
        return resultat

    def lire(self):
        rappels, cache, erreurs = [], {}, []
        for liste in self._listes():
            nom = str(getattr(liste, "title", "") or "Rappels")
            try:  # une liste illisible ne doit pas cacher les autres
                for n, r in enumerate(self._r.get_reminders(calendar=liste, completed=False)):
                    identifiant = str(getattr(r, "identifier", "") or f"{nom}#{n}#{r.title}")
                    cache[identifiant] = r
                    rappels.append(_rappel(identifiant, nom, r.title, getattr(r, "due_date", None)))
            except Exception as e:
                erreurs.append(f"Liste « {nom} » illisible ({type(e).__name__})")
        with self._verrou:
            self._cache, self.erreurs = cache, erreurs
        return rappels

    def terminer(self, identifiant):
        with self._verrou:
            r = self._cache.get(identifiant)
        if r is None:
            return False
        r.completed = True
        r.save()
        return True

    def _liste(self, nom):
        for liste in self._listes():
            if _cle_liste(liste.title) == _cle_liste(nom):
                return liste
        raise ListeIntrouvable(f"Liste « {nom} » introuvable dans Rappels : choisissez-la dans les Réglages.")

    def ajouter(self, nom_liste, titre):
        liste = self._liste(nom_liste)
        deja = {_cle_titre(r.title) for r in self._r.get_reminders(calendar=liste, completed=False)}
        if _cle_titre(titre) in deja:
            return False
        r = self._r.Reminder(liste)
        r.title = titre
        r.save()
        return True

    def terminer_titre(self, nom_liste, titre):
        liste = self._liste(nom_liste)
        for r in self._r.get_reminders(calendar=liste, completed=False):
            if _cle_titre(r.title) == _cle_titre(titre):
                r.completed = True
                r.save()
                return True
        return False


class RappelsSimules:
    """Rappels gardés dans un fichier JSON : {"Liste": [{"titre", "echeance", "fait"}]}."""

    def __init__(self, chemin, listes=()):
        self.chemin = chemin
        self.erreurs = []
        self._verrou = threading.Lock()
        for nom in listes:
            self.creer_liste(nom)

    def _lire(self):
        try:
            with open(self.chemin, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _ecrire(self, donnees):
        os.makedirs(os.path.dirname(os.path.abspath(self.chemin)), exist_ok=True)
        with open(self.chemin, "w", encoding="utf-8") as f:
            json.dump(donnees, f, ensure_ascii=False, indent=1)

    def creer_liste(self, nom):
        with self._verrou:
            d = self._lire()
            d.setdefault(nom, [])
            self._ecrire(d)

    def listes(self):
        return [{"nom": nom, "nombre": sum(1 for r in elements if not r.get("fait")), "erreur": None}
                for nom, elements in self._lire().items()]

    def lire(self):
        rappels = []
        for liste, elements in self._lire().items():
            for n, r in enumerate(elements):
                if not r.get("fait"):
                    rappels.append(_rappel(f"{liste}#{n}", liste, r.get("titre"), r.get("echeance")))
        return rappels

    def terminer(self, identifiant):
        liste, _, n = str(identifiant).rpartition("#")
        with self._verrou:
            d = self._lire()
            try:
                d[liste][int(n)]["fait"] = True
            except (KeyError, IndexError, ValueError):
                return False
            self._ecrire(d)
        return True

    def _nom(self, d, nom):
        trouve = next((k for k in d if _cle_liste(k) == _cle_liste(nom)), None)
        if trouve is None:
            raise ListeIntrouvable(f"Liste « {nom} » introuvable dans Rappels : choisissez-la dans les Réglages.")
        return trouve

    def ajouter(self, nom_liste, titre):
        with self._verrou:
            d = self._lire()
            elements = d[self._nom(d, nom_liste)]
            if any(_cle_titre(r["titre"]) == _cle_titre(titre) and not r.get("fait") for r in elements):
                return False
            elements.append({"titre": titre})
            self._ecrire(d)
        return True

    def terminer_titre(self, nom_liste, titre):
        with self._verrou:
            d = self._lire()
            for r in d[self._nom(d, nom_liste)]:
                if not r.get("fait") and _cle_titre(r["titre"]) == _cle_titre(titre):
                    r["fait"] = True
                    self._ecrire(d)
                    return True
        return False


# ---------------------------------------------------------------- Calendrier

class AgendaIOS:
    """Calendrier de l'iPhone (EventKit), donc aussi Google si le compte est ajouté dans Réglages."""

    # EKAuthorizationStatus : 0 pas encore demandé, 1 restreint, 2 refusé, 3 autorisé, 4 écriture seule
    AUTORISE = 3
    choisis = None  # identifiants des calendriers affichés (None : tous)

    def __init__(self):
        from objc_util import ObjCClass
        self._EKEventStore = ObjCClass("EKEventStore")
        self._NSDate = ObjCClass("NSDate")
        self._NSBundle = ObjCClass("NSBundle")
        self._store = None

    def _cle_plist(self, nom):
        return self._NSBundle.mainBundle().objectForInfoDictionaryKey_(nom) is not None

    def _autoriser(self):
        statut = int(self._EKEventStore.authorizationStatusForEntityType_(0))
        if statut == self.AUTORISE:
            return None
        if statut != 0:
            return "Pythonista n'a pas accès au Calendrier : Réglages > Pythonista > Calendriers."
        from ctypes import c_bool, c_void_p
        from objc_util import ObjCBlock, sel
        fini = threading.Event()

        def reponse(_bloc, _accorde, _erreur):
            fini.set()

        bloc = ObjCBlock(reponse, restype=None, argtypes=[c_void_p, c_bool, c_void_p])
        store = self._EKEventStore.alloc().init()
        # Sans la phrase d'explication dans Pythonista, iOS fermerait l'appli : on vérifie avant de demander.
        if store.respondsToSelector_(sel("requestFullAccessToEventsWithCompletion:")) and self._cle_plist("NSCalendarsFullAccessUsageDescription"):
            store.requestFullAccessToEventsWithCompletion_(bloc)
        elif self._cle_plist("NSCalendarsUsageDescription"):
            store.requestAccessToEntityType_completion_(0, bloc)
        else:
            return "Pythonista ne peut pas lire le Calendrier : indiquez l'adresse iCal de Google dans les Réglages."
        fini.wait(60)
        if int(self._EKEventStore.authorizationStatusForEntityType_(0)) != self.AUTORISE:
            return "Accès au Calendrier refusé : Réglages > Pythonista > Calendriers."
        return None

    def du_jour(self, jour=None):
        jour = jour or datetime.now().astimezone().date()
        evenements, erreurs = self._entre(jour, 1)
        return {"jour": jour.isoformat(), "evenements": evenements, "erreurs": erreurs}

    def semaine(self, debut=None, nombre=7):
        from liens import repartir_par_jour
        debut = debut or datetime.now().astimezone().date()
        evenements, erreurs = self._entre(debut, nombre)
        return {"debut": debut.isoformat(), "jours": repartir_par_jour(evenements, debut, nombre), "erreurs": erreurs}

    def _magasin(self):
        if self._store is None:
            self._store = self._EKEventStore.alloc().init()
        return self._store

    def calendriers(self):
        """Calendriers de l'appareil : [{"id", "nom", "compte"}], triés par compte puis par nom."""
        probleme = self._autoriser()
        if probleme:
            raise ValueError(probleme)
        sortie = []
        for c in self._magasin().calendarsForEntityType_(0) or []:
            source = c.source()
            sortie.append({"id": str(c.calendarIdentifier()), "nom": str(c.title()),
                           "compte": str(source.title()) if source else ""})
        sortie.sort(key=lambda c: (c["compte"].lower(), c["nom"].lower()))
        return sortie

    def _entre(self, jour, nombre):
        probleme = self._autoriser()
        if probleme:
            return [], [probleme]
        magasin = self._magasin()
        debut = datetime.combine(jour, datetime.min.time()).astimezone()
        fin = datetime.combine(jour + timedelta(days=nombre), datetime.min.time()).astimezone()
        calendriers = None  # tous
        if self.choisis:
            gardes = [c for c in magasin.calendarsForEntityType_(0) or [] if str(c.calendarIdentifier()) in self.choisis]
            if gardes:  # calendriers choisis disparus (compte retiré) : on montre tout plutôt que rien
                from objc_util import ns
                calendriers = ns(gardes)
        predicat = magasin.predicateForEventsWithStartDate_endDate_calendars_(
            self._NSDate.dateWithTimeIntervalSince1970_(debut.timestamp()),
            self._NSDate.dateWithTimeIntervalSince1970_(fin.timestamp()), calendriers)
        evenements = []
        for e in self._store.eventsMatchingPredicate_(predicat) or []:
            if int(e.status()) == 3:  # annulé
                continue
            d = datetime.fromtimestamp(float(e.startDate().timeIntervalSince1970())).astimezone()
            f = datetime.fromtimestamp(float(e.endDate().timeIntervalSince1970())).astimezone()
            journee = bool(e.isAllDay())
            lieu = e.location()
            evenements.append({
                "titre": str(e.title() or "(sans titre)")[:200],
                "lieu": str(lieu)[:200] if lieu else "",
                "debut": d.date().isoformat() if journee else d.isoformat(),
                "fin": f.date().isoformat() if journee else f.isoformat(),
                "journee": journee,
                "agenda": str(e.calendar().title()),
            })
        evenements.sort(key=lambda e: (not e["journee"], e["debut"]))
        return evenements, []


class AgendaSimule:
    choisis = None  # noms des agendas affichés (None : tous)

    def __init__(self, evenements=None):
        self.evenements = evenements or []

    def _garder(self, evenements):
        return [e for e in evenements if not self.choisis or e.get("agenda", "Démo") in self.choisis]

    def calendriers(self):
        noms = sorted({e.get("agenda", "Démo") for e in self.evenements or _exemples_semaine(datetime.now().date())})
        return [{"id": n, "nom": n, "compte": "Démonstration"} for n in noms]

    def du_jour(self, jour=None):
        return {"jour": (jour or datetime.now().date()).isoformat(), "evenements": self._garder(self.evenements), "erreurs": []}

    def semaine(self, debut=None, nombre=7):
        from liens import repartir_par_jour
        debut = debut or datetime.now().date()
        evenements = self._garder(list(self.evenements) or _exemples_semaine(debut))
        return {"debut": debut.isoformat(), "jours": repartir_par_jour(evenements, debut, nombre), "erreurs": []}


def _exemples_semaine(debut):
    """Rendez-vous d'exemple pour la démonstration sur ordinateur."""
    exemples = [(0, "09:30", "10:30", "Réunion d'équipe", "Travail"), (1, "18:30", "19:30", "Piscine des enfants", "Famille"),
                (2, "12:30", "14:00", "Déjeuner avec Claire", "Travail"), (4, "20:00", "23:00", "Dîner chez Paul", "Famille")]
    sortie = []
    for n, h1, h2, titre, agenda in exemples:
        jour = (debut + timedelta(days=n)).isoformat()
        sortie.append({"titre": titre, "lieu": "", "debut": f"{jour}T{h1}:00", "fin": f"{jour}T{h2}:00", "journee": False, "agenda": agenda})
    sortie.append({"titre": "Vacances scolaires", "lieu": "", "debut": (debut + timedelta(days=5)).isoformat(),
                   "fin": (debut + timedelta(days=7)).isoformat(), "journee": True, "agenda": "Famille"})
    return sortie


# ---------------------------------------------------------------- Code-barres

class ScannerIOS:
    """Photo avec l'appareil photo, puis lecture du code-barres par la reconnaissance d'images d'Apple (Vision)."""

    TYPES = ("EAN13", "EAN8", "UPCE", "UPCA")

    def __init__(self):
        import photos  # noqa: F401  (vérifie que l'on est dans Pythonista)
        from objc_util import ObjCClass
        self._Requete = ObjCClass("VNDetectBarcodesRequest")
        self._Lecteur = ObjCClass("VNImageRequestHandler")

    def scanner(self):
        """Renvoie le texte du code-barres, ou None si la photo est annulée. Lève ValueError si rien n'est lu."""
        import io
        import photos
        from objc_util import ns
        image = photos.capture_image()
        if image is None:
            return None
        image = image.convert("RGB")
        image.thumbnail((2000, 2000))
        tampon = io.BytesIO()
        image.save(tampon, "JPEG", quality=90)
        requete = self._Requete.alloc().init()
        lecteur = self._Lecteur.alloc().initWithData_options_(ns(tampon.getvalue()), ns({}))
        lecteur.performRequests_error_(ns([requete]), None)
        codes = []
        for resultat in requete.results() or []:
            texte = resultat.payloadStringValue()
            if texte:
                codes.append((str(resultat.symbology()), str(texte)))
        # les codes de produits (EAN, UPC) passent avant les QR codes
        codes.sort(key=lambda c: not any(t in c[0].upper() for t in self.TYPES))
        if not codes:
            raise ValueError("Aucun code-barres lu sur la photo : rapprochez-vous et évitez les reflets.")
        return codes[0][1]


# ---------------------------------------------------------------- Écran

class EcranIOS:
    """Garde l'écran allumé (mode cadre) tant que l'appli est ouverte."""

    def __init__(self):
        import console
        self._console = console

    def garder_allume(self, actif):
        self._console.set_idle_timer_disabled(bool(actif))


# ---------------------------------------------------------------- iCloud Drive

class ICloudIOS:
    """Demande à iOS la dernière version d'un fichier iCloud avant de le lire.

    Sans cela, l'iPad peut lire une ancienne copie du placard, ou rien du tout si le fichier
    n'est encore qu'un « .etat.json.icloud » (pas téléchargé).
    """

    CLE = "NSURLUbiquitousItemDownloadingStatusKey"
    A_JOUR = "NSURLUbiquitousItemDownloadingStatusCurrent"

    def __init__(self):
        from objc_util import ObjCClass
        self._gestionnaire = ObjCClass("NSFileManager").defaultManager()
        self._URL = ObjCClass("NSURL")
        self._derniers = {}
        self._verrou = threading.Lock()

    def _statut(self, chemin):
        from objc_util import ns
        valeurs = self._URL.fileURLWithPath_(chemin).resourceValuesForKeys_error_(ns([self.CLE]), None)
        valeur = valeurs.objectForKey_(self.CLE) if valeurs else None
        return str(valeur) if valeur else None

    def statut(self, chemin):
        """« a_jour », « ancienne » (une version plus récente attend dans iCloud), « pas_telechargee », ou None (hors iCloud)."""
        dossier, nom = os.path.split(chemin)
        if not os.path.exists(chemin) and os.path.exists(os.path.join(dossier, f".{nom}.icloud")):
            return "pas_telechargee"
        statut = self._statut(chemin)
        if statut is None:
            return None
        return "a_jour" if statut == self.A_JOUR else "ancienne" if statut.endswith("Downloaded") else "pas_telechargee"

    def rafraichir(self, chemin, attente=6.0, forcer=False):
        with self._verrou:
            maintenant = time.monotonic()
            if not forcer and maintenant - self._derniers.get(chemin, -60) < 3:  # pas plus d'une demande toutes les 3 secondes
                return
            self._derniers[chemin] = maintenant
        self._gestionnaire.startDownloadingUbiquitousItemAtURL_error_(self._URL.fileURLWithPath_(chemin), None)
        dossier, nom = os.path.split(chemin)
        fantome = os.path.join(dossier, f".{nom}.icloud")
        # fichier pas encore téléchargé : on attend jusqu'à `attente` secondes ; copie un peu ancienne : 1,5 seconde au plus
        fin = time.monotonic() + (attente if os.path.exists(fantome) else 1.5)
        while time.monotonic() < fin:
            if os.path.exists(fantome) and not os.path.exists(chemin):
                time.sleep(0.25)
                continue
            statut = self._statut(chemin)
            if statut is None or statut == self.A_JOUR:
                return
            time.sleep(0.25)


def nom_appareil():
    """« iPhone » ou « iPad » (nom affiché dans les Réglages pour savoir qui a modifié le placard)."""
    try:
        from objc_util import ObjCClass
        return str(ObjCClass("UIDevice").currentDevice().model())
    except Exception:
        import platform
        return platform.node() or "Ordinateur"


# ---------------------------------------------------------------- Réglages secrets

class CoffreIOS:
    """Trousseau de l'appareil (module keychain de Pythonista) : les clés ne quittent pas l'iPhone."""

    SERVICE, COMPTE = "Maison", "reglages"

    def __init__(self):
        import keychain
        self._k = keychain

    def lire(self):
        try:
            return json.loads(self._k.get_password(self.SERVICE, self.COMPTE) or "{}")
        except ValueError:
            return {}

    def ecrire(self, reglages):
        self._k.set_password(self.SERVICE, self.COMPTE, json.dumps(reglages))


class CoffreFichier:
    """Réglages dans un fichier (ordinateur et tests uniquement)."""

    def __init__(self, chemin):
        self.chemin = chemin

    def lire(self):
        try:
            with open(self.chemin, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def ecrire(self, reglages):
        os.makedirs(os.path.dirname(os.path.abspath(self.chemin)), exist_ok=True)
        with open(self.chemin, "w", encoding="utf-8") as f:
            json.dump(reglages, f)
