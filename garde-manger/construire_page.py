"""Construit la version statique de Garde-manger pour GitHub Pages.

    python construire_page.py [dossier_de_sortie]      (par défaut : _site)

La page est générée à partir de donnees.py et de templates/index.html.
Dans cette version, le placard est enregistré dans le navigateur de chaque
appareil, et les fonctions Claude sont désactivées (aucune clé API ne doit
être publiée dans une page web).
"""

import hashlib
import json
import os
import shutil
import sys

import donnees

DOSSIER = os.path.dirname(os.path.abspath(__file__))
MARQUEUR = "/*__GARDE_MANGER__*/null"
SOUS_DOSSIER = "garde-manger"

# Garde l'appli disponible sans réseau : la page est rechargée quand le réseau
# répond, sinon la dernière version enregistrée est affichée.
SERVICE_WORKER = """const CACHE = 'garde-manger-%(version)s';
const FICHIERS = ['./', 'manifest.webmanifest', 'static/apple-touch-icon.png', 'static/icone-192.png', 'static/icone-512.png'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(FICHIERS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== location.origin) return;
  e.respondWith(
    fetch(req).then(r => {
      if (r.ok) { const copie = r.clone(); caches.open(CACHE).then(c => c.put(req, copie)); }
      return r;
    }).catch(() => caches.match(req, {ignoreSearch: true}).then(r => r || caches.match('./')))
  );
});
"""

ACCUEIL = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="0; url=garde-manger/">
<title>Domotique Home Lab</title></head>
<body><p><a href="garde-manger/">Ouvrir Garde-manger</a></p></body></html>
"""


def page_statique():
    with open(os.path.join(DOSSIER, "templates", "index.html"), encoding="utf-8") as f:
        page = f.read()
    if MARQUEUR not in page:
        raise RuntimeError("templates/index.html ne contient pas le marqueur des données")
    injecte = {"donnees": donnees.pour_interface(), "etat": {}, "version": 0, "claude": False, "statique": True}
    texte = json.dumps(injecte, ensure_ascii=False).replace("</", "<\\/")
    return page.replace(MARQUEUR, texte)


def construire(sortie):
    if os.path.isdir(sortie):
        shutil.rmtree(sortie)
    appli = os.path.join(sortie, SOUS_DOSSIER)
    shutil.copytree(os.path.join(DOSSIER, "static"), os.path.join(appli, "static"))
    shutil.move(os.path.join(appli, "static", "manifest.webmanifest"), os.path.join(appli, "manifest.webmanifest"))
    page = page_statique()
    with open(os.path.join(appli, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    version = hashlib.sha256(page.encode("utf-8")).hexdigest()[:12]
    with open(os.path.join(appli, "sw.js"), "w", encoding="utf-8") as f:
        f.write(SERVICE_WORKER % {"version": version})
    with open(os.path.join(sortie, "index.html"), "w", encoding="utf-8") as f:
        f.write(ACCUEIL)
    open(os.path.join(sortie, ".nojekyll"), "w").close()
    return appli


if __name__ == "__main__":
    dossier = construire(sys.argv[1] if len(sys.argv) > 1 else "_site")
    print(f"Page construite dans {dossier}")
