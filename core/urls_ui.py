"""URLs (vues du NAVIGATEUR) des briques embarquées en iframe + clé du compte Studio.

S128 — Les briques embarquées doivent s'afficher à la fois en LAN
(`http://192.168.1.89:5100`) et depuis un pair du mesh (`https://100.124.248.226`),
SANS repointer une IP figée (qui casserait l'autre accès, cf.
`docs/sprints/S128-briques-embarquees-acces-distant.md`). On ne fige donc plus
d'URL absolue par brique : on garde `{port, chemin}` et on préfixe, à la volée, avec
le **scheme + l'hôte de la requête courante** (`url_brique`). Une surcharge par env
(`<NOM>_UI_URL`) reste possible (repli / cas SSO Forge / déploiement particulier).

Partagé par le router `dashboard` (iframes) et `usine` (GENERATEUR_URL_PUBLIQUE).
"""
import os

# Table des briques embarquées : NOM -> (port hôte, chemin de la SPA). Le port reste
# identique en LAN et sur le mesh (Caddy expose chaque port en HTTPS), donc aucune
# ré-écriture de chemin — les SPA gardent leurs assets à la racine de leur port.
# Port 6060 et pas 6000 pour le Studio : 6000 = X11, banni par Chrome (ERR_UNSAFE_PORT).
BRIQUES_UI = {
    "FORGE":         (3000, "/"),          # SPA Forge (SSO Keycloak géré DANS la SPA)
    "STUDIO":        (6060, "/atelier"),
    "PERSONNAGES":   (5900, "/atelier"),
    "TRANSCRIPTION": (5980, "/atelier"),
    "RESTAURANT":    (6010, "/"),          # multi-tenant, clé de service
    "MAIL":          (6030, "/"),
    "SYNOPSIS":      (6090, "/"),
    "VOIX":          (5985, "/"),          # WebSocket (test Piper/Kokoro) — Caddy fait l'upgrade
    "MEMOIRE":       (5600, "/memory"),    # SPA + proxy /api/v1 same-origin
    "DEV_IDE":       (8744, "/"),          # code-server (auth propre + WS) — différé S128
    "GATEWAY":       (4001, "/ui"),        # console LiteLLM (peut poser X-Frame-Options)
    "GENERATEUR":    (5400, "/bundles-studio"),  # composeur de bundles embarqué (tuile Atelier)
    "PEERTUBE":      (9000, "/"),          # hébergement vidéo souverain
}


def _nom_env(nom: str) -> str:
    """Nom de la variable d'env de SURCHARGE d'une brique. Historiquement
    `<NOM>_UI_URL`, sauf l'IDE dev, resté `DEV_IDE_URL`."""
    return "DEV_IDE_URL" if nom == "DEV_IDE" else f"{nom}_UI_URL"


def _hote_sans_port(host: str) -> str:
    """Renvoie l'hôte de l'en-tête `Host` sans le `:port` éventuel
    (`192.168.1.89:5100` -> `192.168.1.89`, `100.124.248.226` inchangé)."""
    host = (host or "localhost").strip()
    if host.startswith("["):                       # IPv6 littéral, ex. [::1]:5100
        return host.split("]", 1)[0] + "]"
    return host.rsplit(":", 1)[0] if ":" in host else host


def url_brique(nom: str, scheme: str, host: str) -> str:
    """URL (vue navigateur) de la brique `nom`.

    Surcharge env `<NOM>_UI_URL` si posée (déploiement particulier / SSO), sinon
    construite depuis le scheme + l'hôte de la REQUÊTE courante — la même logique
    donne la bonne URL en LAN, sur le mesh (HTTPS/Caddy) et en dev local (S128).

    Accès distant via le mesh : quand la requête arrive par l'hôte mesh (`MESH_HOST`),
    les briques sont servies en **HTTPS par Caddy sur des ports DÉCALÉS**
    (`MESH_PORT_OFFSET`, défaut 10000). Nécessaire car le port réel reste occupé par
    Docker (`0.0.0.0:<port>`) → Caddy ne peut pas réutiliser le même port sur l'IP mesh.
    En LAN / dev (MESH_HOST vide ou hôte différent), on sert le port réel en direct.
    """
    surcharge = os.environ.get(_nom_env(nom))
    if surcharge:
        return surcharge
    port, chemin = BRIQUES_UI[nom]
    hote = _hote_sans_port(host)
    mesh_host = os.environ.get("MESH_HOST", "").strip()
    if mesh_host and hote == mesh_host:
        offset = int(os.environ.get("MESH_PORT_OFFSET", "10000"))
        return f"https://{hote}:{port + offset}{chemin}"
    return f"{scheme}://{hote}:{port}{chemin}"


# URL publique du Générateur (liens « aperçu / télécharger » du tableau des entreprises
# livrées, ouverts dans un NOUVEL onglet — hors iframe). Reste pilotée par env : un lien
# vers un nouvel onglet ne dépend pas de l'hôte de l'iframe courante.
GENERATEUR_URL_PUBLIQUE = os.environ.get("GENERATEUR_URL_PUBLIQUE", "http://localhost:5400")

# « Compte Studio » = clé de service partagée avec la brique (auth X-API-Key). Quand elle est
# définie, l'iframe du dashboard la transporte en `?api_key=` (le front Studio la lit).
# Cockpit mono-opérateur : la clé EST l'identité (même frontière de confiance que /dashboard).
STUDIO_KEY = os.environ.get("STUDIO_KEY", "")
