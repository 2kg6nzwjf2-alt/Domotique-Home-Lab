"""Accès à l'iPhone ou l'iPad depuis Pythonista : Rappels, Calendrier et trousseau.

Chaque source a deux versions :
- « IOS » : utilisée dans Pythonista (modules reminders, keychain et objc_util) ;
- « Simulé » : utilisée sur un ordinateur et dans les tests, avec des fichiers JSON.
"""

import json
import os
import threading
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
        probleme = self._autoriser()
        if probleme:
            return {"evenements": [], "erreurs": [probleme]}
        if self._store is None:
            self._store = self._EKEventStore.alloc().init()
        maintenant = datetime.now().astimezone()
        debut = datetime.combine(jour or maintenant.date(), datetime.min.time()).astimezone()
        fin = debut + timedelta(days=1)
        predicat = self._store.predicateForEventsWithStartDate_endDate_calendars_(
            self._NSDate.dateWithTimeIntervalSince1970_(debut.timestamp()),
            self._NSDate.dateWithTimeIntervalSince1970_(fin.timestamp()), None)
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
        return {"jour": debut.date().isoformat(), "evenements": evenements, "erreurs": []}


class AgendaSimule:
    def __init__(self, evenements=None):
        self.evenements = evenements or []

    def du_jour(self, jour=None):
        return {"jour": (jour or datetime.now().date()).isoformat(), "evenements": list(self.evenements), "erreurs": []}


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
