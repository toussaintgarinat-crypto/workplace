"""Routes « systeme » du Cœur (extrait de main.py, S114).

Santé, registre des briques, capacités, horloge, MCP, assets PWA.
"""
import logging
import os
import json
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from etat import registre
import assistant
import catalogue
import familles as familles_mod
import horloge
import mcp as mcp_serveur
import outils
import routage_outils

router = APIRouter()


@router.get("/health", tags=["système"])
def health():
    return {"statut": "ok", "version": "0.2.0", "briques_chargees": len(registre.briques)}


@router.get("/briques", tags=["briques"])
def lister_briques(grouper: str | None = None):
    """Liste toutes les briques enregistrées.

    `?grouper=famille` → dict groupé par famille (label, icone, briques[]).
    Sans paramètre → liste plate (comportement historique)."""
    briques = list(registre.briques.values())
    if grouper == "famille":
        return familles_mod.grouper(briques)
    return {"total": len(briques), "briques": briques}


@router.get("/briques/{nom}", tags=["briques"])
def detail_brique(nom: str):
    """Détail d'une brique par son nom."""
    brique = registre.briques.get(nom)
    if not brique:
        raise HTTPException(status_code=404, detail=f"Brique '{nom}' introuvable")
    return brique


@router.post("/briques/reload", tags=["briques"])
async def recharger_briques():
    """Recharge tous les manifests sans redémarrer le cœur.

    Réindexe AUSSI le routage d'outils par embeddings (best-effort) : sans ça, une capacité
    ajoutée à une brique resterait invisible au LLM (pas de vecteur à l'index → jamais routée)
    jusqu'au prochain redémarrage du Cœur."""
    registre.charger()
    reindexe = False
    try:
        reindexe = await routage_outils.indexer(outils.outils_pour(registre))
    except Exception:  # noqa: BLE001 — le routage ne doit jamais faire échouer un reload
        logging.getLogger(__name__).warning("Routage d'outils : réindexation ignorée", exc_info=True)
    return {"statut": "ok", "briques_chargees": len(registre.briques), "routage_reindexe": reindexe}


@router.post("/mcp", tags=["mcp"])
async def mcp_endpoint(request: Request):
    """Gateway MCP (JSON-RPC 2.0) : point d'entrée unique pour des clients/agents tiers.

    Expose les MÊMES outils que l'assistant (statiques + capacités découvertes par manifest)
    et le co-agent planificateur (`coagent_lancer`). Auth par `MCP_KEY` si définie. Accepte un
    message JSON-RPC ou un lot ; une notification (sans `id`) ne renvoie pas de corps (202)."""
    if not mcp_serveur.actif():
        raise HTTPException(404, "Serveur MCP désactivé (MCP_ACTIF=0).")
    presentee = (request.headers.get("x-api-key")
                 or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
                 or None)
    if not mcp_serveur.cle_ok(presentee):
        raise HTTPException(401, "Clé MCP manquante ou invalide (header X-API-Key).")
    try:
        corps = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Corps JSON-RPC illisible.")
    if isinstance(corps, list):                       # lot JSON-RPC
        reps = [r for r in [await mcp_serveur.traiter(m, registre) for m in corps]
                if r is not None]
        return JSONResponse(reps) if reps else Response(status_code=202)
    rep = await mcp_serveur.traiter(corps, registre)
    if rep is None:                                   # notification → pas de corps
        return Response(status_code=202)
    return JSONResponse(rep)


@router.get("/capacites", tags=["briques"])
def lister_capacites():
    """Catalogue des capacités appelables découvertes dans les manifests (S63).

    Le « schéma corporel » : ce que le Cœur sait faire en agrégeant le champ `capacites`
    de chaque brique. Inspection seule — le câblage au LLM est le sujet de S64."""
    cap = catalogue.collecter_capacites(registre)
    return {
        "total": len(cap),
        "briques": sorted({c["brique"] for c in cap}),
        "doublons": catalogue.doublons(cap),
        "capacites": cap,
    }


@router.get("/briques/{nom}/sante", tags=["briques"])
async def sante_brique(nom: str):
    """Ping le endpoint de santé d'une brique (si url_sante définie)."""
    brique = registre.briques.get(nom)
    if not brique:
        raise HTTPException(status_code=404, detail=f"Brique '{nom}' introuvable")
    url = brique.get("url_sante")
    if not url:
        return {"nom": nom, "statut": "non_applicable", "message": "Pas d'url_sante définie dans le manifest"}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(url)
            statut = "ok" if r.status_code < 400 else "erreur"
            return {"nom": nom, "statut": statut, "code_http": r.status_code}
    except Exception as e:
        return {"nom": nom, "statut": "inaccessible", "erreur": str(e)}


@router.get("/horloge/taches", tags=["horloge"])
def horloge_taches():
    """Tâches périodiques déclarées par les briques (manifest `taches`) avec, pour
    chacune, sa cadence, sa dernière exécution et sa prochaine échéance (S29)."""
    taches = horloge.lister_etat(registre)
    return {"total": len(taches), "taches": taches}


@router.post("/horloge/executer", tags=["horloge"])
async def horloge_executer(forcer: bool = False, brique: str | None = None,
                           tache: str | None = None):
    """Déclenche les tâches dues maintenant. `forcer=true` ignore la cadence ;
    `brique`/`tache` restreignent à une seule tâche (utile pour tester ou rejouer)."""
    return await horloge.run_due(registre, forcer=forcer,
                                 filtre_brique=brique, filtre_tache=tache)


@router.get("/manipulation_directe.js", tags=["système"], include_in_schema=False)
async def socle_manipulation_directe():
    """Socle « manipulation directe » (S101/S102) servi au dashboard : menu contextuel,
    modale de confirmation et cliquer-déposer. Source unique synchronisée par
    outils/sync_socle.sh (cf. en-tête du fichier)."""
    from fastapi.responses import FileResponse
    # Le fichier vit à la racine de core/ ; ce router est dans core/routers/ → on remonte d'un cran.
    chemin = os.path.join(os.path.dirname(os.path.dirname(__file__)), "manipulation_directe.js")
    return FileResponse(chemin, media_type="application/javascript")


@router.get("/workplace.css", tags=["système"], include_in_schema=False)
async def design_system():
    """Design system Workplace (S123) servi au dashboard : tokens visuels partagés.
    Source unique = shared/static/workplace.css, copié ici par outils/sync_socle.sh."""
    from fastapi.responses import FileResponse
    # Le fichier vit à la racine de core/ ; ce router est dans core/routers/ → on remonte d'un cran.
    chemin = os.path.join(os.path.dirname(os.path.dirname(__file__)), "workplace.css")
    return FileResponse(chemin, media_type="text/css")


# ── PWA « télécommande » (S61) : dashboard installable sur mobile, plein écran ──────
# Le téléphone n'est qu'une télécommande : zéro calcul/stockage lourd, juste l'UI de chat
# (streaming S60) qui parle au Cœur. Motif éprouvé de la brique transcription.
_PWA_MANIFEST = {
    "name": "Workplace — Cœur", "short_name": "Workplace",
    "description": "Télécommande de la solution : piloter, discuter, capter — depuis le mobile.",
    "start_url": "/dashboard", "scope": "/", "display": "standalone",
    "background_color": "#0f1117", "theme_color": "#0f1117",
    "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml",
               "purpose": "any maskable"}],
}

_PWA_SW = """// Service worker minimal : coque hors-ligne au lancement, API toujours réseau.
const C = 'workplace-coeur-v1';
self.addEventListener('install', e => {
  e.waitUntil(caches.open(C).then(c => c.addAll(['/dashboard', '/icon.svg'])));
  self.skipWaiting();
});
self.addEventListener('activate', e => { e.waitUntil(self.clients.claim()); });
self.addEventListener('fetch', e => {
  const r = e.request;
  if (r.method !== 'GET') return;                 // POST /assistant/chat, etc. → réseau direct
  if (r.mode === 'navigate') {                     // lancement de l'app → coque en repli si hors-ligne
    e.respondWith(fetch(r).catch(() => caches.match('/dashboard')));
  }
});
"""

_PWA_ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
             '<rect width="512" height="512" rx="96" fill="#0f1117"/>'
             '<circle cx="256" cy="256" r="120" fill="none" stroke="#7c83ff" stroke-width="22"/>'
             '<circle cx="256" cy="256" r="46" fill="#7c83ff"/></svg>')


@router.get("/manifest.webmanifest", include_in_schema=False)
def pwa_manifest():
    return Response(json.dumps(_PWA_MANIFEST), media_type="application/manifest+json")


@router.get("/sw.js", include_in_schema=False)
def pwa_service_worker():
    return Response(_PWA_SW, media_type="application/javascript")


@router.get("/icon.svg", include_in_schema=False)
def pwa_icon():
    return Response(_PWA_ICON, media_type="image/svg+xml")


@router.get("/sante-globale", tags=["système"])
async def sante_globale():
    """Ping toutes les briques qui ont une url_sante."""
    resultats = {}
    async with httpx.AsyncClient(timeout=3.0) as client:
        for nom, brique in registre.briques.items():
            url = brique.get("url_sante")
            info: dict = {"famille": brique.get("famille", "autre")}
            if not url:
                resultats[nom] = {**info, "statut": "non_applicable"}
                continue
            try:
                r = await client.get(url)
                resultats[nom] = {**info, "statut": "ok" if r.status_code < 400 else "erreur", "code_http": r.status_code}
            except Exception as e:
                resultats[nom] = {**info, "statut": "inaccessible", "erreur": str(e)}
    return {"briques": resultats}


# ── Usine à applications (S5) ────────────────────────────────────────────────
# Le Cœur pilote la chaîne ETL→Audit→Génération(→Packaging) en une commande et
# tient le tableau des entreprises livrées.
