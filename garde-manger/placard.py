"""Résumé du placard pour le tableau de bord : courses, produits à finir, dates de péremption
et une idée de recette qui utilise d'abord ce qui doit être fini."""

from datetime import date

import donnees

BIENTOT = 3  # jours : un produit qui se périme dans 3 jours ou moins est signalé
PRIORITE = 2  # jours : dans 2 jours ou moins, ses recettes passent en premier


def jours_restants(dlc, aujourdhui):
    """Nombre de jours avant la date limite (négatif si dépassée), ou None si pas de date valable."""
    try:
        return (date.fromisoformat(str(dlc)[:10]) - aujourdhui).days
    except (TypeError, ValueError):
        return None


_INTERFACE = None


def _interface():
    global _INTERFACE
    if _INTERFACE is None:
        _INTERFACE = donnees.pour_interface()
    return _INTERFACE


def _recettes():
    """[(nom, minutes, ingrédients obligatoires, tous les ingrédients)] du carnet."""
    sortie = []
    for r in _interface()["recettes"]:  # [nom, minutes, personnes, type, difficulté, ingrédients, étapes]
        nom, minutes, ings = r[0], r[1], r[5]
        cles = [str(i).lstrip("?").split(":")[0] for i in ings]
        obligatoires = [str(i).split(":")[0] for i in ings if not str(i).startswith("?")]
        sortie.append((nom, minutes, obligatoires, cles))
    return sortie


def _labels():
    return {i[0]: i[1] for i in _interface()["ingredients"]}


def idee_recette(placard, prioritaires):
    """Recette faisable (1 ingrédient manquant au plus) qui utilise le plus de produits prioritaires."""
    if not prioritaires:
        return None
    present = {p.get("id") for p in placard if isinstance(p, dict)}
    meilleure = None
    for nom, minutes, obligatoires, cles in _recettes():
        utilises = [k for k in dict.fromkeys(cles) if k in prioritaires]
        if not utilises:
            continue
        manque = [k for k in obligatoires if k not in present]
        if len(manque) > 1:
            continue
        cle = (len(manque), -len(utilises), minutes)
        if meilleure is None or cle < meilleure[0]:
            meilleure = (cle, nom, utilises, manque)
    if meilleure is None:
        return None
    _, nom, utilises, manque = meilleure
    labels = _labels()
    return {"nom": nom, "utilise": [prioritaires[k] for k in utilises],
            "manque": [labels.get(k, k) for k in manque]}


def resume(etat, aujourdhui=None):
    aujourdhui = aujourdhui or date.today()
    courses = etat.get("courses") if isinstance(etat.get("courses"), list) else []
    placard = [p for p in (etat.get("pantry") if isinstance(etat.get("pantry"), list) else []) if isinstance(p, dict)]
    peremption, prioritaires = [], {}
    for p in placard:
        label = str(p.get("label", ""))[:60]
        jours = jours_restants(p.get("dlc"), aujourdhui)
        if jours is not None and jours <= BIENTOT:
            peremption.append({"label": label, "dlc": str(p["dlc"])[:10], "jours": jours})
        if p.get("urgent") or (jours is not None and jours <= PRIORITE):
            prioritaires[p.get("id")] = label
    peremption.sort(key=lambda x: x["jours"])
    return {
        "courses": [str(c.get("label", ""))[:60] for c in courses if isinstance(c, dict)][:50],
        "a_finir": [str(p.get("label", ""))[:60] for p in placard if p.get("urgent")][:20],
        "placard": len(placard),
        "peremption": peremption[:20],
        "idee": idee_recette(placard, prioritaires),
    }
