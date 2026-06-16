"""Réglages *runtime* du « cerveau » de l'assistant — pilotables depuis le front.

Objectif : changer le **modèle** LLM et la **clé OpenRouter** sans éditer de
fichier ni lancer de commande à la main.

- Le **modèle** (et ses fallbacks) est persisté dans un petit JSON, dans le
  volume du Cœur. `assistant.py` le relit à CHAQUE requête → effet immédiat,
  aucun redémarrage.
- La **clé OpenRouter** vit dans l'environnement de la Gateway (`briques/gateway/.env`,
  monté en lecture/écriture dans le Cœur). La changer réécrit ce `.env` puis
  **recrée** le conteneur de la Gateway via l'**API Docker** (socket monté) — un
  simple *restart* ne relirait PAS l'env (Docker le fige à la création), la clé
  resterait l'ancienne. Une petite complétion valide ensuite que la clé fonctionne
  vraiment (honnêteté technique).
"""

import asyncio
import json
import os
from pathlib import Path

import httpx

CONFIG_PATH = Path(os.getenv("ASSISTANT_CONFIG_PATH", "/data/assistant_config.json"))
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://host.docker.internal:4001")
GATEWAY_KEY = os.environ["GATEWAY_KEY"]  # requis — défini dans le .env racine (plus de défaut public)
GATEWAY_ENV_PATH = Path(os.getenv("GATEWAY_ENV_PATH", "/gateway/.env"))
GATEWAY_PROJET = os.getenv("GATEWAY_COMPOSE_PROJECT", "gateway")
DOCKER_SOCK = os.getenv("DOCKER_SOCK", "/var/run/docker.sock")

DEFAUT_MODEL = os.getenv("GATEWAY_MODEL", "openai/gpt-4o-mini")
DEFAUT_FALLBACKS = [m.strip() for m in os.getenv("FALLBACK_MODELS", "").split(",") if m.strip()]

# Cascade auto (cost-first) : au lieu d'un modèle figé, l'assistant essaie d'abord les
# meilleurs modèles GRATUITS servis par la Gateway (auto-sélectionnés, function-calling),
# puis bascule sur un repli payant fiable. Les gratuits étant bornés côté Gateway
# (timeout court), le fail-over est rapide. Choisir un modèle dans ⚙ Cerveau le place
# EN TÊTE de la cascade (ex. une IA locale, ou inverser vers le payant d'abord).
DEFAUT_CASCADE_AUTO = os.getenv("CASCADE_AUTO", "1").lower() not in ("0", "false", "no")
DEFAUT_REPLI_PAYANT = os.getenv("REPLI_PAYANT", "deepseek/deepseek-v4-flash")
DEFAUT_CASCADE_FREE_N = int(os.getenv("CASCADE_FREE_N", "3"))

# Routage dynamique (S138, chantier 1) : pour les requêtes triviales, rétrograder
# vers un modèle économe SANS changer le modèle configuré. Désactivé par défaut
# (kill-switch = comportement statique). `modele_econome` vide → premier `free/*`.
DEFAUT_ROUTAGE_ACTIF = os.getenv("ROUTAGE_ACTIF", "0").lower() not in ("0", "false", "no")
DEFAUT_MODELE_ECONOME = os.getenv("MODELE_ECONOME", "")

# Summarization à froid (S138, chantier 3b) : condenser l'historique long via un
# petit modèle plutôt que de le couper. Désactivé par défaut. `modele_resume` vide
# → premier `free/*` des fallbacks.
DEFAUT_RESUME_ACTIF = os.getenv("RESUME_ACTIF", "0").lower() not in ("0", "false", "no")
DEFAUT_MODELE_RESUME = os.getenv("MODELE_RESUME", "")

# Shadow routing (S138, chantier 4) : sur un échantillon, rejouer un candidat moins
# cher en tâche de fond pour mesurer l'équivalence. Désactivé par défaut.
DEFAUT_SHADOW_ACTIF = os.getenv("SHADOW_ACTIF", "0").lower() not in ("0", "false", "no")
DEFAUT_SHADOW_CANDIDAT = os.getenv("SHADOW_CANDIDAT", "")
DEFAUT_SHADOW_TAUX = float(os.getenv("SHADOW_TAUX", "0.05"))

# Voix : fournisseur de parole temps réel. 'webspeech' = navigateur (défaut, 0 infra) ;
# 'unmute' = serveur Kyutai Unmute (nécessite un GPU NVIDIA, cf. outils/unmute/) ;
# 'wakeword' = mot-clé « comme Siri » via la brique ecoute (S42, openWakeWord, CPU).
DEFAUT_VOIX_PROVIDER = os.getenv("VOIX_PROVIDER", "webspeech")
DEFAUT_UNMUTE_URL = os.getenv("UNMUTE_URL", "")
# URL WebSocket de la brique ecoute (S42). Défaut = brique locale exposée sur 5800.
DEFAUT_WAKEWORD_URL = os.getenv("WAKEWORD_URL", "ws://localhost:5800/ecoute")

# Muscle déporté (roadmap « partage de puissance de calcul », brique calcul port 5990) :
# si actif, le Cœur demande à calcul quel nœud de calcul distant est PRÊT et le met EN
# TÊTE de la cascade ; sinon il déclenche un réveil EN FOND et sert la requête courante
# en mode dégradé (gratuits). Désactivé par défaut (opt-in) → comportement inchangé.
DEFAUT_MUSCLE_ACTIF = os.getenv("MUSCLE_ACTIF", "0").lower() not in ("0", "false", "no")

# Repli souverain CPU sur le Cœur (S62) : dernier maillon de la cascade quand le Muscle
# dort et que les gratuits échouent — un petit modèle 100 % local (modèle Gateway
# `local/cpu` p.ex.). Vide = désactivé. `avant_payant` = souveraineté d'abord (on tente
# le local AVANT d'envoyer les données au payant cloud).
DEFAUT_REPLI_SOUVERAIN = os.getenv("REPLI_SOUVERAIN", "")
DEFAUT_REPLI_SOUVERAIN_AVANT_PAYANT = \
    os.getenv("REPLI_SOUVERAIN_AVANT_PAYANT", "1").lower() not in ("0", "false", "no")

# Langue du Jarvis (S39) : langue de ses réponses (chat/briefing/résumé/classement)
# ET de la voix (reco/synthèse). Préférence de l'utilisateur, réglable ⚙ Cerveau,
# défaut `fr`. La normalisation/repli est dans `langue.py` (source de vérité).
DEFAUT_LANGUE = os.getenv("ASSISTANT_LANGUE", "fr")


# ── Modèle + voix (persistés, lus à chaud) ──────────────────────────────────
def charger() -> dict:
    """Renvoie {model, fallback_models, voix_provider, unmute_url}.

    Valeurs par défaut = variables d'env. La voix est réglable depuis le front
    (panneau ⚙ Cerveau) ; le passage webspeech→unmute est ainsi une simple config."""
    base = {
        "model": DEFAUT_MODEL,
        "fallback_models": list(DEFAUT_FALLBACKS),
        "voix_provider": DEFAUT_VOIX_PROVIDER,
        "unmute_url": DEFAUT_UNMUTE_URL,
        "wakeword_url": DEFAUT_WAKEWORD_URL,
        "persona": "default",
        "langue": DEFAUT_LANGUE,
        "routage_actif": DEFAUT_ROUTAGE_ACTIF,
        "modele_econome": DEFAUT_MODELE_ECONOME,
        "resume_actif": DEFAUT_RESUME_ACTIF,
        "modele_resume": DEFAUT_MODELE_RESUME,
        "shadow_actif": DEFAUT_SHADOW_ACTIF,
        "shadow_candidat": DEFAUT_SHADOW_CANDIDAT,
        "shadow_taux": DEFAUT_SHADOW_TAUX,
        "cascade_auto": DEFAUT_CASCADE_AUTO,
        "repli_payant": DEFAUT_REPLI_PAYANT,
        "cascade_free_n": DEFAUT_CASCADE_FREE_N,
        "muscle_actif": DEFAUT_MUSCLE_ACTIF,
        "repli_souverain": DEFAUT_REPLI_SOUVERAIN,
        "repli_souverain_avant_payant": DEFAUT_REPLI_SOUVERAIN_AVANT_PAYANT,
    }
    if CONFIG_PATH.exists():
        try:
            d = json.loads(CONFIG_PATH.read_text())
            base["model"] = d.get("model") or base["model"]
            base["fallback_models"] = d.get("fallback_models") or base["fallback_models"]
            base["voix_provider"] = d.get("voix_provider") or base["voix_provider"]
            if d.get("unmute_url") is not None:
                base["unmute_url"] = d.get("unmute_url")
            if d.get("wakeword_url") is not None:
                base["wakeword_url"] = d.get("wakeword_url")
            base["persona"] = d.get("persona") or base["persona"]
            base["langue"] = d.get("langue") or base["langue"]
            if d.get("routage_actif") is not None:
                base["routage_actif"] = bool(d.get("routage_actif"))
            if d.get("modele_econome") is not None:
                base["modele_econome"] = d.get("modele_econome")
            if d.get("resume_actif") is not None:
                base["resume_actif"] = bool(d.get("resume_actif"))
            if d.get("modele_resume") is not None:
                base["modele_resume"] = d.get("modele_resume")
            if d.get("shadow_actif") is not None:
                base["shadow_actif"] = bool(d.get("shadow_actif"))
            if d.get("shadow_candidat") is not None:
                base["shadow_candidat"] = d.get("shadow_candidat")
            if d.get("shadow_taux") is not None:
                base["shadow_taux"] = float(d.get("shadow_taux"))
            if d.get("cascade_auto") is not None:
                base["cascade_auto"] = bool(d.get("cascade_auto"))
            if d.get("repli_payant") is not None:
                base["repli_payant"] = d.get("repli_payant")
            if d.get("cascade_free_n") is not None:
                base["cascade_free_n"] = int(d.get("cascade_free_n"))
            if d.get("muscle_actif") is not None:
                base["muscle_actif"] = bool(d.get("muscle_actif"))
            if d.get("repli_souverain") is not None:
                base["repli_souverain"] = d.get("repli_souverain")
            if d.get("repli_souverain_avant_payant") is not None:
                base["repli_souverain_avant_payant"] = bool(d.get("repli_souverain_avant_payant"))
        except Exception:
            pass
    return base


def definir_routage(actif: bool | None = None, modele_econome: str | None = None) -> dict:
    """Active/désactive le routage dynamique (S138-1) et fixe le modèle économe."""
    conf = charger()
    if actif is not None:
        conf["routage_actif"] = bool(actif)
    if modele_econome is not None:
        conf["modele_econome"] = modele_econome.strip()
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(conf, ensure_ascii=False, indent=2))
    return conf


def definir_muscle(actif: bool | None = None) -> dict:
    """Active/désactive le recours au muscle déporté (brique calcul, roadmap S58)."""
    conf = charger()
    if actif is not None:
        conf["muscle_actif"] = bool(actif)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(conf, ensure_ascii=False, indent=2))
    return conf


def definir_repli_souverain(modele: str | None = None,
                            avant_payant: bool | None = None) -> dict:
    """Règle le repli souverain CPU (S62) : modèle Gateway local + position vs payant."""
    conf = charger()
    if modele is not None:
        conf["repli_souverain"] = modele.strip()
    if avant_payant is not None:
        conf["repli_souverain_avant_payant"] = bool(avant_payant)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(conf, ensure_ascii=False, indent=2))
    return conf


def definir_modele(model: str | None, fallbacks: list[str] | None = None) -> dict:
    conf = charger()
    if model is not None:  # "" autorisé = aucune tête de cascade (cascade gratuite pure)
        conf["model"] = model.strip()
    if fallbacks is not None:
        conf["fallback_models"] = [m.strip() for m in fallbacks if m and m.strip()]
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(conf, ensure_ascii=False, indent=2))
    return conf


def definir_persona(persona: str | None) -> dict:
    """Règle la personnalité de l'assistant (cf. core/personas.py)."""
    conf = charger()
    if persona:
        conf["persona"] = persona
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(conf, ensure_ascii=False, indent=2))
    return conf


def definir_langue(langue: str | None) -> dict:
    """Règle la langue du Jarvis (réponses + voix), normalisée/repli `fr` via langue.py."""
    import langue as langue_mod  # import tardif : évite tout cycle au chargement
    conf = charger()
    if langue:
        conf["langue"] = langue_mod.normaliser(langue)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(conf, ensure_ascii=False, indent=2))
    return conf


def definir_voix(provider: str | None, unmute_url: str | None = None,
                 wakeword_url: str | None = None) -> dict:
    """Règle le fournisseur de voix ('webspeech'|'unmute'|'wakeword') et les URLs de
    serveur (Unmute full-duplex, brique ecoute S42)."""
    conf = charger()
    if provider in ("webspeech", "unmute", "wakeword"):
        conf["voix_provider"] = provider
    if unmute_url is not None:
        conf["unmute_url"] = unmute_url.strip()
    if wakeword_url is not None:
        conf["wakeword_url"] = wakeword_url.strip()
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(conf, ensure_ascii=False, indent=2))
    return conf


async def lister_modeles() -> list[str]:
    """Modèles exposés par la Gateway (pour peupler le menu déroulant du front)."""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{GATEWAY_URL}/v1/models",
                            headers={"Authorization": f"Bearer {GATEWAY_KEY}"})
            r.raise_for_status()
            return [m["id"] for m in r.json().get("data", [])]
    except Exception:
        return []


def definir_cascade(actif: bool | None = None, repli: str | None = None,
                    n: int | None = None) -> dict:
    """Règle la cascade auto (gratuits → repli payant) du cerveau."""
    conf = charger()
    if actif is not None:
        conf["cascade_auto"] = bool(actif)
    if repli is not None:
        conf["repli_payant"] = repli.strip()
    if n is not None:
        conf["cascade_free_n"] = max(0, int(n))
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(conf, ensure_ascii=False, indent=2))
    return conf


async def chaine_modeles(conf: dict | None = None) -> list[str]:
    """Ordre effectif des modèles essayés par l'assistant (dédupliqué, ordre conservé).

    Mode **cascade auto** (défaut) : [modèle choisi s'il y en a un] → meilleurs GRATUITS
    servis par la Gateway (top N, function-calling, bornés) → repli payant fiable. Choisir
    un modèle dans ⚙ Cerveau le met EN TÊTE (ex. IA locale d'abord ; ou le payant pour
    inverser). Si aucun gratuit n'est servi, on tombe directement sur le repli payant.

    Mode **manuel** (cascade_auto=false) : comportement historique [modèle] + fallbacks.
    """
    conf = conf or charger()
    principal = (conf.get("model") or "").strip()
    # Repli souverain CPU (S62) : dernier maillon LOCAL. Placé avant ou après le repli
    # payant selon la préférence (souveraineté d'abord = avant le cloud).
    souverain = (conf.get("repli_souverain") or "").strip()
    souverain_avant = conf.get("repli_souverain_avant_payant", True)

    if not conf.get("cascade_auto"):
        # Mode manuel : le souverain est l'ultime filet, en toute fin de chaîne.
        chaine = ([principal] if principal else []) + list(conf.get("fallback_models") or []) \
            + ([souverain] if souverain else [])
    else:
        dispo = await lister_modeles()
        gratuits = [m for m in dispo if m.startswith("free/")][: conf.get("cascade_free_n", 3)]
        repli = (conf.get("repli_payant") or DEFAUT_REPLI_PAYANT).strip()
        queue = []
        if souverain and souverain_avant:
            queue += [souverain] + ([repli] if repli else [])
        elif souverain:
            queue += ([repli] if repli else []) + [souverain]
        else:
            queue += [repli] if repli else []
        chaine = ([principal] if principal else []) + gratuits + queue

    # Dédup en conservant l'ordre ; on retire les vides.
    vu: set[str] = set()
    ordre: list[str] = []
    for m in chaine:
        if m and m not in vu:
            vu.add(m)
            ordre.append(m)
    return ordre


# ── Clé OpenRouter (env de la Gateway) ──────────────────────────────────────
def _lire_cle() -> str:
    if not GATEWAY_ENV_PATH.exists():
        return ""
    for ligne in GATEWAY_ENV_PATH.read_text().splitlines():
        if ligne.startswith("OPENROUTER_API_KEY="):
            return ligne.split("=", 1)[1].strip()
    return ""


def cle_openrouter_definie() -> bool:
    cle = _lire_cle()
    return bool(cle) and "change" not in cle.lower() and cle not in ("sk-or-...", "")


def _ecrire_cle(cle: str) -> None:
    """Réécrit (ou ajoute) la ligne OPENROUTER_API_KEY dans le .env de la Gateway."""
    lignes: list[str] = []
    trouve = False
    if GATEWAY_ENV_PATH.exists():
        for ligne in GATEWAY_ENV_PATH.read_text().splitlines():
            if ligne.startswith("OPENROUTER_API_KEY="):
                lignes.append(f"OPENROUTER_API_KEY={cle}")
                trouve = True
            else:
                lignes.append(ligne)
    if not trouve:
        lignes.append(f"OPENROUTER_API_KEY={cle}")
    GATEWAY_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    GATEWAY_ENV_PATH.write_text("\n".join(lignes) + "\n")


# ── Pilotage Docker de la Gateway (via le socket, sans dépendance externe) ───
def _docker_client() -> httpx.AsyncClient:
    transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCK)
    return httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=60)


async def recreer_gateway() -> bool:
    """Recrée le conteneur de la Gateway pour qu'il relise son environnement.

    Pourquoi recréer et non redémarrer : Docker FIGE l'env d'un conteneur à sa
    création. Un `/restart` relance le process avec l'ancien env → la nouvelle clé
    OpenRouter (déjà écrite dans le `.env`) serait ignorée. On réinjecte donc la clé
    fraîche dans l'`Env` et on recrée le conteneur à l'identique (même nom, image,
    montages, réseaux, healthcheck, politique de redémarrage).

    Filet de sécurité : on renomme l'ancien AVANT de créer le nouveau ; si la
    création échoue, on restaure l'ancien (jamais de Gateway perdue).
    On ne touche que les conteneurs portant `OPENROUTER_API_KEY` (la Gateway, pas la
    base de données). False si aucun conteneur du projet n'est trouvé.
    """
    nouvelle_cle = _lire_cle()
    filtres = json.dumps({"label": [f"com.docker.compose.project={GATEWAY_PROJET}"]})
    async with _docker_client() as d:
        r = await d.get("/containers/json", params={"all": "true", "filters": filtres})
        r.raise_for_status()
        if not r.json():
            return False
        cibles = []
        for resume in r.json():
            insp = (await d.get(f"/containers/{resume['Id']}/json")).json()
            if any(e.startswith("OPENROUTER_API_KEY=") for e in (insp["Config"].get("Env") or [])):
                cibles.append(insp)
        for insp in cibles:
            await _recreer_conteneur(d, insp, nouvelle_cle)
    return True


async def _recreer_conteneur(d: httpx.AsyncClient, insp: dict, nouvelle_cle: str) -> None:
    """Recrée un conteneur à l'identique en remplaçant sa clé OpenRouter."""
    ancien_id = insp["Id"]
    court = ancien_id[:12]
    nom = insp["Name"].lstrip("/")
    cfg = insp["Config"]
    env = [f"OPENROUTER_API_KEY={nouvelle_cle}" if e.startswith("OPENROUTER_API_KEY=") else e
           for e in (cfg.get("Env") or [])]
    reseaux = (insp.get("NetworkSettings") or {}).get("Networks") or {}

    def _alias(ep: dict) -> list[str]:  # on retire l'alias = id court de l'ANCIEN conteneur
        return [a for a in (ep.get("Aliases") or []) if a != court]

    corps = {
        "Image": cfg.get("Image"),
        "Env": env,
        "Labels": cfg.get("Labels"),
        "Cmd": cfg.get("Cmd"),
        "Entrypoint": cfg.get("Entrypoint"),
        "WorkingDir": cfg.get("WorkingDir"),
        "ExposedPorts": cfg.get("ExposedPorts"),
        "Volumes": cfg.get("Volumes"),
        "Healthcheck": cfg.get("Healthcheck"),
        "HostConfig": insp.get("HostConfig"),
    }
    premier = next(iter(reseaux), None)
    if premier:
        corps["NetworkingConfig"] = {"EndpointsConfig": {premier: {"Aliases": _alias(reseaux[premier])}}}

    # Arrêt + renommage de l'ancien (filet de sécurité avant la création).
    await d.post(f"/containers/{ancien_id}/stop", params={"t": "5"})
    await d.post(f"/containers/{ancien_id}/rename", params={"name": f"{nom}_old"})
    try:
        cr = await d.post("/containers/create", params={"name": nom}, json=corps)
        cr.raise_for_status()
        nouvel_id = cr.json()["Id"]
        # Réseaux supplémentaires (Docker n'en accepte qu'un à la création).
        for nom_reseau, ep in reseaux.items():
            if nom_reseau == premier:
                continue
            await d.post(f"/networks/{nom_reseau}/connect",
                         json={"Container": nouvel_id, "EndpointConfig": {"Aliases": _alias(ep)}})
        await d.post(f"/containers/{nouvel_id}/start")
    except Exception:
        # Échec → on restaure l'ancien (renommage inverse + redémarrage) et on remonte.
        await d.post(f"/containers/{ancien_id}/rename", params={"name": nom})
        await d.post(f"/containers/{ancien_id}/start")
        raise
    # Succès → l'ancien (renommé) ne sert plus.
    await d.delete(f"/containers/{ancien_id}")


async def attendre_gateway(timeout: int = 45) -> bool:
    async with httpx.AsyncClient(timeout=5) as c:
        for _ in range(timeout):
            try:
                r = await c.get(f"{GATEWAY_URL}/v1/models",
                                headers={"Authorization": f"Bearer {GATEWAY_KEY}"})
                if r.status_code < 500:
                    return True
            except Exception:
                pass
            await asyncio.sleep(1)
    return False


async def tester_modele(model: str) -> tuple[bool, str]:
    """Petite complétion réelle : prouve que le modèle (et la clé) répond vraiment.

    Passe par le pipeline unifié (S138) — sans fallback (un seul modèle testé) ni
    trimming — pour que même les pings comptent dans le journal d'usage."""
    import llm_pipeline  # import tardif : évite tout cycle au chargement du module
    res = await llm_pipeline.completer(
        [{"role": "user", "content": "ping"}],
        modeles=[model], max_tokens=5, etiquette="test", trim_contexte=False,
        timeout=30,
    )
    if res.ok:
        return True, "Le modèle répond."
    return False, res.erreur or "Le modèle ne répond pas."
