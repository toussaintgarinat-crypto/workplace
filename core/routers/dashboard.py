"""Routes « dashboard » du Cœur (extrait de main.py, S114).

Tableau de bord visuel du Cœur : sert `core/dashboard.html` en y injectant les URLs des
iframes, construites depuis la requête courante (S128).
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
import auth
import jeu_factions_jeton
import memoire_jeton
from etat import registre
from urls_ui import GENERATEUR_URL_PUBLIQUE, GEO_KEY, PERSONNAGES_KEY, url_brique

# Le gabarit vit dans `dashboard.html`, à côté, et non dans une chaîne Python (S208).
# Il faisait 3460 des 3527 lignes de ce module — du HTML/CSS/JS sans coloration, sans
# linting, et que toute modification de l'UI du Cœur obligeait à éditer au milieu du code.
# Motif déjà employé par toutes les briques à front (`front.html` + FileResponse).
#
# Lu une seule fois à l'import : le fichier est livré DANS l'image, il ne change pas en
# cours d'exécution, et le relire à chaque requête coûterait une E/S par affichage.
_GABARIT = (Path(__file__).parent.parent / "dashboard.html").read_text(encoding="utf-8")




router = APIRouter()


@router.get("/dashboard", tags=["système"], response_class=HTMLResponse)
async def dashboard(request: Request):
    """Interface visuelle du registre de briques."""
    # S128 — Les URLs des iframes (__*_UI_URL__) sont construites depuis le scheme + l'hôte
    # de la REQUÊTE courante (pas figées dans le template ni sur une IP), pour que les mêmes
    # tuiles s'affichent en LAN (http://192.168.1.89:5100), sur le mesh (https://100.x via
    # Caddy) et en dev local. X-Forwarded-Proto prime derrière Caddy (le Cœur sert en HTTP
    # interne). Une surcharge env `<NOM>_UI_URL` reste possible (repli / SSO Forge).
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("host", "localhost")

    def u(nom):
        return url_brique(nom, scheme, host)

    # Studio (S187) : vue native via le proxy /studio-app/* du Cœur (même origine, session
    # déjà posée), PAR PERSONNE — PAS l'URL brute + STUDIO_KEY statique (qui retombait sur le
    # même tenant partagé par tout le foyer, trou S183). Motif mail S185.
    studio_ui = "/studio-app/"
    # Atelier Images & Vidéo : même motif que Studio (proxy Cœur, session, isolation par
    # personne) — PAS l'URL brute :6160 (qui contournerait l'injection X-User-Id de session
    # et exposerait un accès mono-tenant non isolé, même trou que S183 un cran plus loin,
    # cf. core/routers/atelier_images_video_proxy.py).
    atelier_images_video_ui = "/atelier-images-video-app/atelier"
    # Même motif pour GeoHub : le front carte lit `?api_key=` (X-API-Key sur ses fetch).
    geo_ui = u("GEO")
    if GEO_KEY:
        sep = "&" if "?" in geo_ui else "?"
        geo_ui = f"{geo_ui}{sep}api_key={GEO_KEY}"
    # Même motif pour l'atelier Personnages (5900) : ses fronts lisent `?api_key=` et le
    # posent en X-API-Key sur tous leurs fetch (lister/créer/éditer fiches, casting, geo…).
    # Sans cela, dès que PERSONNAGES_KEY est posée, le front tire 401 partout (clé manquante).
    personnages_ui = u("PERSONNAGES")
    if PERSONNAGES_KEY:
        sep = "&" if "?" in personnages_ui else "?"
        personnages_ui = f"{personnages_ui}{sep}api_key={PERSONNAGES_KEY}"
    # Mémoire (S186) : jeton signé PAR PERSONNE (pas une clé statique partagée comme
    # ci-dessus) — dit à la brique QUI ouvre l'onglet sans exposer MEMOIRE_KEY au navigateur.
    # emettre() renvoie None si MEMOIRE_KEY n'est pas configurée : l'URL reste inchangée, la
    # brique retombe sur le compte de service (comportement historique, mono-tenant).
    memoire_ui = u("MEMOIRE")
    jeton_memoire = memoire_jeton.emettre(auth.sub_session_optionnel(request) or "perso")
    if jeton_memoire:
        sep = "&" if "?" in memoire_ui else "?"
        memoire_ui = f"{memoire_ui}{sep}m={jeton_memoire}"
    # Jeu-factions (S217) : même motif jeton signé que Mémoire. Contrairement à Mémoire, PAS
    # de repli mono-tenant si JEU_FACTIONS_KEY est absente — la brique refuse tout sans jeton
    # valide (spec S217, Non-objectifs), donc la tuile reste simplement inutilisable.
    jeu_factions_ui = u("JEU_FACTIONS")
    jeton_jf = jeu_factions_jeton.emettre(auth.sub_session_optionnel(request) or "perso")
    if jeton_jf:
        sep = "&" if "?" in jeu_factions_ui else "?"
        jeu_factions_ui = f"{jeu_factions_ui}{sep}j={jeton_jf}"
    return HTMLResponse(content=_GABARIT
        .replace("__FORGE_UI_URL__", u("FORGE"))
        .replace("__STUDIO_UI_URL__", studio_ui)
        .replace("__ATELIER_IMAGES_VIDEO_UI_URL__", atelier_images_video_ui)
        .replace("__PERSONNAGES_UI_URL__", personnages_ui)
        .replace("__TRANSCRIPTION_UI_URL__", u("TRANSCRIPTION"))
        .replace("__RESTAURANT_UI_URL__", u("RESTAURANT"))
        .replace("__MAIL_UI_URL__", u("MAIL"))
        .replace("__AGENDA_UI_URL__", u("AGENDA"))
        .replace("__GEO_UI_URL__", geo_ui)
        .replace("__ATELIER_VEILLE_UI_URL__", "/atelier-veille-app/atelier")
        .replace("__SYNOPSIS_UI_URL__", u("SYNOPSIS"))
        .replace("__VOIX_UI_URL__", u("VOIX"))
        .replace("__MEMOIRE_UI_URL__", memoire_ui)
        .replace("__DEV_IDE_URL__", u("DEV_IDE"))
        .replace("__GENERATEUR_BUNDLES_URL__", u("GENERATEUR"))
        .replace("__GATEWAY_UI_URL__", u("GATEWAY"))
        .replace("__JEU_FACTIONS_UI_URL__", jeu_factions_ui))
