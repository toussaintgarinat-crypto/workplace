import json
import os
import re
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from generateur import generer_app_complete
from gabarit import entites_du_plan, generer_html
from langues import normaliser_langue
import oria_provisioning
import client_provisioning
import pont_crm
import packager
import revue
import appliquer

AUDIT_URL = os.getenv("AUDIT_URL", "http://host.docker.internal:5300")
DB_PATH = os.getenv("DB_PATH", "/data/apps.db")
EXPORT_DIR = os.getenv("EXPORT_DIR", "/export")

# Brique « donnees » (persistance serveur). Deux URLs :
#  - INTERNE : appelée par CE service (générateur) pour semer les données → réseau Docker.
#  - PUBLIQUE : injectée dans l'app générée, appelée depuis le NAVIGATEUR de l'utilisateur.
DONNEES_URL_INTERNE = os.getenv("DONNEES_URL_INTERNE", "http://host.docker.internal:5500")
DONNEES_URL_PUBLIQUE = os.getenv("DONNEES_URL_PUBLIQUE", "http://localhost:5500")

# Source de la brique « donnees » (montée en lecture seule dans le conteneur générateur),
# copiée dans chaque bundle de déploiement pour un build 100 % reproductible (S4).
DONNEES_SRC = os.getenv("DONNEES_SRC", "/briques_src/donnees")

# Brique « oria » (messagerie). URLs PUBLIQUES injectées dans l'app (appelées depuis le
# navigateur de l'utilisateur). Le SSO réutilise le client Keycloak `oria-app`.
ORIA_URL_PUBLIQUE = os.getenv("ORIA_URL_PUBLIQUE", "http://localhost:8000")
MATRIX_URL_PUBLIQUE = os.getenv("MATRIX_URL_PUBLIQUE", "http://localhost:8010")
KEYCLOAK_URL_PUBLIQUE = os.getenv("KEYCLOAK_URL_PUBLIQUE", "http://localhost:8081")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "oria")
ORIA_CLIENT_ID = os.getenv("ORIA_CLIENT_ID", "oria-app")


def _slug(nom: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (nom or "app").lower()).strip("-")
    return s or "app"


# ── Base de données ────────────────────────────────────────────────────────────

def _connexion() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    with _connexion() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS apps (
                id             TEXT PRIMARY KEY,
                date_creation  TEXT NOT NULL,
                audit_id       TEXT NOT NULL,
                nom_entreprise TEXT,
                plan           TEXT,
                html           TEXT,
                statut         TEXT DEFAULT 'en_cours',
                erreur         TEXT,
                mode           TEXT DEFAULT 'autonome',
                oria_world_id  TEXT,
                oria_salons    TEXT
            )
        """)
        # Migrations : ajoute les colonnes aux bases déjà créées sans elles.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(apps)").fetchall()}
        if "mode" not in cols:
            conn.execute("ALTER TABLE apps ADD COLUMN mode TEXT DEFAULT 'autonome'")
        if "oria_world_id" not in cols:
            conn.execute("ALTER TABLE apps ADD COLUMN oria_world_id TEXT")
        if "oria_salons" not in cols:
            conn.execute("ALTER TABLE apps ADD COLUMN oria_salons TEXT")
        if "client_onboarding" not in cols:
            conn.execute("ALTER TABLE apps ADD COLUMN client_onboarding TEXT")
        if "partage_forge" not in cols:
            # Consentement du pont app→CRM (S24) : {actif, entites:[...]}. Opt-in : Non par défaut.
            conn.execute("ALTER TABLE apps ADD COLUMN partage_forge TEXT")
        if "revue" not in cols:
            # Dernière revue « app vivante » (S31) : {statut, proposition, date}. Null tant
            # qu'aucune revue n'a tourné. La proposition est à valider avant toute génération.
            conn.execute("ALTER TABLE apps ADD COLUMN revue TEXT")
        if "langue" not in cols:
            # Langue de l'app livrée (S37), fixée à la livraison. Défaut/repli 'fr'.
            conn.execute("ALTER TABLE apps ADD COLUMN langue TEXT DEFAULT 'fr'")
        conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_db()
    yield


app = FastAPI(title="Générateur d'app", version="0.2.0", lifespan=lifespan)


# ── Tâche de fond ──────────────────────────────────────────────────────────────

async def _semer_donnees(app_id: str, plan: dict):
    """Pré-remplit la brique « donnees » avec les exemples du plan (mode hébergé).

    Idempotent côté serveur : ne réécrase pas une entité déjà peuplée.
    """
    for ent in entites_du_plan(plan):
        exemples = [e for e in ent.get("exemples", []) if isinstance(e, dict)]
        if not exemples:
            continue
        url = f"{DONNEES_URL_INTERNE}/apps/{app_id}/entites/{ent['id']}/seed"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(url, json={"enregistrements": exemples})
        except Exception as e:
            print(f"[generateur] seed donnees échoué pour {ent['id']}: {e}")


def _provisionner_messagerie(audit: dict) -> dict | None:
    """Provisionne l'espace Oria de l'entreprise (best-effort).

    Retourne la config Oria à injecter dans l'app, ou None si Oria est injoignable
    (l'app est alors générée sans messagerie, sans planter la génération).
    """
    nom = audit.get("nom_entreprise", "Entreprise")
    try:
        carte = oria_provisioning.provisionner_espace(nom, audit)
    except Exception as e:
        print(f"[generateur] provisioning Oria échoué ({nom}) : {e} — app sans messagerie")
        return None
    return {
        "world_id": carte["world_id"],
        "salons": [{"nom": s["nom"], "matrix_room_id": s["matrix_room_id"]}
                   for s in carte["salons"] if s.get("matrix_room_id")],
        # Config navigateur (SSO + endpoints publics)
        "oria_api": ORIA_URL_PUBLIQUE,
        "matrix": MATRIX_URL_PUBLIQUE,
        "keycloak": {
            "url": KEYCLOAK_URL_PUBLIQUE,
            "realm": KEYCLOAK_REALM,
            "clientId": ORIA_CLIENT_ID,
        },
    }


async def _generer_en_background(app_id: str, audit: dict, mode: str, messagerie: bool,
                                 email_client: str | None = None,
                                 contact_client: str | None = None,
                                 langue: str = "fr"):
    try:
        hebergee = mode == "hebergee"
        api_base = DONNEES_URL_PUBLIQUE if hebergee else ""

        oria_cfg = None
        if hebergee and messagerie:
            # Provisioning synchrone (httpx.Client) hors boucle asyncio.
            import anyio
            oria_cfg = await anyio.to_thread.run_sync(_provisionner_messagerie, audit)

        plan, html = await generer_app_complete(
            audit, app_id=(app_id if hebergee else ""), api_base=api_base, oria=oria_cfg,
            langue=langue,
        )
        if hebergee:
            await _semer_donnees(app_id, plan)

        # Compte client auto (S23) : à la livraison, on onboarde le client (best-effort).
        onboarding = None
        if email_client:
            import anyio
            nom_ent = audit.get("nom_entreprise", "Entreprise")
            onboarding = await anyio.to_thread.run_sync(
                client_provisioning.creer_compte_client,
                email_client, contact_client or "",
                (oria_cfg or {}).get("world_id"), nom_ent,
            )
            print(f"[generateur] onboarding client {email_client} : {onboarding.get('message')}")

        with _connexion() as conn:
            conn.execute(
                "UPDATE apps SET plan=?, html=?, statut='termine', oria_world_id=?, "
                "oria_salons=?, client_onboarding=? WHERE id=?",
                (json.dumps(plan, ensure_ascii=False), html,
                 (oria_cfg or {}).get("world_id"),
                 json.dumps((oria_cfg or {}).get("salons", []), ensure_ascii=False) if oria_cfg else None,
                 json.dumps(onboarding, ensure_ascii=False) if onboarding else None,
                 app_id),
            )
            conn.commit()
    except Exception as e:
        with _connexion() as conn:
            conn.execute(
                "UPDATE apps SET statut='erreur', erreur=? WHERE id=?",
                (str(e), app_id),
            )
            conn.commit()


# ── Modèles ────────────────────────────────────────────────────────────────────

class DemandeGeneration(BaseModel):
    audit_id: str
    # "autonome" = 1 fichier HTML + localStorage (mono-poste) ;
    # "hebergee" = persistance serveur via la brique « donnees » (multi-utilisateur).
    persistance: str = "autonome"
    # Messagerie interne Oria (espace + salons par entreprise). N'a de sens qu'en mode
    # hébergé ; ignorée en autonome.
    messagerie: bool = True
    # Compte client auto (S23) : si fourni, on crée à la livraison un compte d'accès
    # Keycloak à cet email + on lui envoie un lien « définis ton mot de passe » et on le
    # rattache à son espace Oria. Best-effort (n'interrompt pas la génération).
    email_client: str | None = None
    contact_client: str | None = None
    # Langue de l'app livrée (S37), fixée à la livraison. 'fr' (défaut) | 'en' | 'es' | 'ar'.
    # Toute valeur inconnue retombe sur 'fr' (repli honnête).
    langue: str = "fr"


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.post("/generer", status_code=202)
async def generer(demande: DemandeGeneration, background_tasks: BackgroundTasks):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{AUDIT_URL}/audits/{demande.audit_id}")
            r.raise_for_status()
            audit = r.json()
    except Exception as e:
        raise HTTPException(404, f"Audit introuvable ou brique Audit inaccessible : {e}")

    if audit.get("statut") != "termine":
        raise HTTPException(400, f"L'audit n'est pas terminé (statut : {audit.get('statut')})")

    mode = "hebergee" if demande.persistance == "hebergee" else "autonome"
    langue = normaliser_langue(demande.langue)
    app_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    nom = audit.get("nom_entreprise", "Entreprise")

    with _connexion() as conn:
        conn.execute(
            "INSERT INTO apps (id, date_creation, audit_id, nom_entreprise, statut, mode, langue) "
            "VALUES (?,?,?,?,?,?,?)",
            (app_id, now, demande.audit_id, nom, "en_cours", mode, langue),
        )
        conn.commit()

    background_tasks.add_task(_generer_en_background, app_id, audit, mode,
                              demande.messagerie, demande.email_client,
                              demande.contact_client, langue)
    return {"id": app_id, "statut": "en_cours", "nom_entreprise": nom, "mode": mode,
            "langue": langue,
            "messagerie": bool(mode == "hebergee" and demande.messagerie),
            "compte_client": bool(demande.email_client)}


@app.get("/apps")
def lister_apps():
    with _connexion() as conn:
        rows = conn.execute(
            "SELECT id, date_creation, audit_id, nom_entreprise, statut, mode FROM apps ORDER BY date_creation DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/apps/{app_id}")
def lire_app(app_id: str):
    with _connexion() as conn:
        row = conn.execute(
            "SELECT id, date_creation, audit_id, nom_entreprise, plan, statut, erreur, mode, "
            "langue, oria_world_id, oria_salons, client_onboarding, partage_forge FROM apps WHERE id=?",
            (app_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "App non trouvée")
    d = dict(row)
    for champ in ("plan", "oria_salons", "client_onboarding", "partage_forge"):
        if d.get(champ):
            try:
                d[champ] = json.loads(d[champ])
            except Exception:
                pass
    return d


class PartageForge(BaseModel):
    # Consentement du pont app→CRM (S24). Opt-in : actif=False par défaut.
    actif: bool = False
    entites: list[str] = []  # liste blanche des entités à remonter


def _lire_partage(app_id: str) -> dict:
    with _connexion() as conn:
        row = conn.execute("SELECT partage_forge FROM apps WHERE id=?", (app_id,)).fetchone()
    if not row:
        raise HTTPException(404, "App non trouvée")
    try:
        return json.loads(row["partage_forge"]) if row["partage_forge"] else {"actif": False, "entites": []}
    except Exception:
        return {"actif": False, "entites": []}


def _ecrire_partage(app_id: str, config: dict) -> None:
    with _connexion() as conn:
        conn.execute(
            "UPDATE apps SET partage_forge=? WHERE id=?",
            (json.dumps(config, ensure_ascii=False), app_id),
        )
        conn.commit()


@app.put("/apps/{app_id}/partage-forge")
def definir_partage_forge(app_id: str, corps: PartageForge):
    """Règle le consentement du **pont app→CRM** (S24) et l'applique immédiatement.

    `actif=True` + `entites=[...]` → les enregistrements de ces entités remontent dans
    le CRM du cabinet (idempotent). `actif=False` (défaut) → rien ne sort. La remontée
    est best-effort : l'app reste livrée même si le Forge est injoignable.
    """
    config = {"actif": bool(corps.actif), "entites": list(corps.entites or [])}
    _ecrire_partage(app_id, config)
    rapport = pont_crm.pousser(app_id, config) if config["actif"] else {
        "actif": False, "pousses": 0, "message": "partage désactivé — rien ne sort"
    }
    print(f"[generateur] partage Forge {app_id} : {rapport.get('message')}")
    return {"partage_forge": config, "remontee": rapport}


@app.post("/apps/{app_id}/partage-forge/revoquer")
def revoquer_partage_forge(app_id: str, purger: bool = False):
    """Révoque le consentement : arrête le pont. `purger=true` ⇒ efface aussi du CRM
    les prospects déjà remontés (décision : purge sur demande explicite uniquement)."""
    config = _lire_partage(app_id)
    config["actif"] = False
    _ecrire_partage(app_id, config)
    rapport = pont_crm.revoquer(app_id, purger=purger)
    print(f"[generateur] révocation partage Forge {app_id} : {rapport.get('message')}")
    return {"partage_forge": config, "revocation": rapport}


# ── Revue « app vivante » (S31) — re-audit post-livraison ────────────────────────

def _charger_app(app_id: str) -> dict:
    with _connexion() as conn:
        row = conn.execute(
            "SELECT id, audit_id, nom_entreprise, plan, partage_forge, revue FROM apps WHERE id=?",
            (app_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "App non trouvée")
    d = dict(row)
    for champ in ("plan", "partage_forge", "revue"):
        if d.get(champ):
            try:
                d[champ] = json.loads(d[champ])
            except Exception:
                pass
    return d


async def _charger_audit(audit_id: str) -> dict:
    if not audit_id:
        return {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{AUDIT_URL}/audits/{audit_id}")
            r.raise_for_status()
            return r.json()
    except Exception as e:
        print(f"[generateur] audit {audit_id} injoignable pour la revue : {e}")
        return {}


class DemandeRevue(BaseModel):
    # Textes de nouveaux documents observés depuis la livraison (optionnel) — nourrissent
    # le re-audit en plus des données d'usage.
    nouveaux_docs: list[str] = []


async def _revue_app(app_id: str, app_row: dict, nouveaux_docs: list[str]) -> dict:
    """Mesure l'usage consenti + propose un incrément pour UNE app, et persiste la revue
    au statut « propose ». Partagé par la revue manuelle (S31) et le balayage horloge (S33).
    NE GÉNÈRE RIEN.
    """
    plan = app_row.get("plan") or {}
    partage = app_row.get("partage_forge") or {"actif": False, "entites": []}

    usage = revue.mesurer_usage(app_id, plan, partage)
    audit = await _charger_audit(app_row.get("audit_id"))
    proposition = await revue.proposer_increment(audit, plan, usage, nouveaux_docs)

    enregistrement = {
        "statut": "propose",
        "date": datetime.now(timezone.utc).isoformat(),
        "usage": usage,
        "proposition": proposition,
    }
    with _connexion() as conn:
        conn.execute("UPDATE apps SET revue=? WHERE id=?",
                     (json.dumps(enregistrement, ensure_ascii=False), app_id))
        conn.commit()
    print(f"[generateur] revue {app_id} : {usage.get('message')} — "
          f"proposition {proposition.get('source')}")
    return enregistrement


@app.post("/apps/{app_id}/revue")
async def lancer_revue(app_id: str, corps: DemandeRevue | None = None):
    """Re-audit post-livraison (S31) : mesure l'usage **consenti**, re-audite et
    **propose** un incrément. NE GÉNÈRE RIEN — la proposition (statut « propose ») doit
    être validée via `/revue/valider` avant toute (re)génération.
    """
    corps = corps or DemandeRevue()
    app_row = _charger_app(app_id)
    enregistrement = await _revue_app(app_id, app_row, corps.nouveaux_docs)
    return {"app_id": app_id, **enregistrement}


@app.post("/revues/balayage")
async def balayer_revues():
    """Revue périodique de **toutes** les apps livrées (S33) — déclenchée par l'horloge S29.

    Pour chaque app au **consentement actif** (souveraineté : sans consentement, aucune
    mesure), mesure l'usage et **propose** un incrément (statut « propose »). Best-effort :
    une app en erreur n'interrompt pas le balayage. **Ne valide ni n'applique rien** — la
    chaîne humaine (S31 valider → S32 appliquer) reste intacte. Pour ne pas écraser une
    décision en attente, on **saute** les apps dont la revue est déjà « validee »
    (incrément validé mais pas encore appliqué).
    """
    with _connexion() as conn:
        rows = conn.execute(
            "SELECT id, audit_id, plan, partage_forge, revue FROM apps"
        ).fetchall()

    proposees, ignorees, erreurs = [], [], []
    for row in rows:
        app_id = row["id"]
        try:
            partage = json.loads(row["partage_forge"]) if row["partage_forge"] else {}
        except Exception:
            partage = {}
        try:
            rev_actuelle = json.loads(row["revue"]) if row["revue"] else None
        except Exception:
            rev_actuelle = None
        eligible, raison = revue.doit_reviser(partage, rev_actuelle)
        if not eligible:
            ignorees.append({"app_id": app_id, "raison": raison})
            continue

        app_row = {
            "audit_id": row["audit_id"],
            "plan": json.loads(row["plan"]) if row["plan"] else {},
            "partage_forge": partage,
        }
        try:
            enr = await _revue_app(app_id, app_row, [])
            proposees.append({"app_id": app_id,
                              "source": enr["proposition"].get("source"),
                              "message": enr["usage"].get("message")})
        except Exception as e:
            print(f"[generateur] balayage revue {app_id} échoué : {e}")
            erreurs.append({"app_id": app_id, "detail": str(e)})

    return {"balayees": len(rows), "proposees": proposees,
            "ignorees": ignorees, "erreurs": erreurs}


@app.get("/apps/{app_id}/revue")
def lire_revue(app_id: str):
    """Dernière revue produite pour l'app (ou statut « aucune » si jamais lancée)."""
    app_row = _charger_app(app_id)
    rev = app_row.get("revue")
    if not rev:
        return {"app_id": app_id, "statut": "aucune"}
    return {"app_id": app_id, **rev}


@app.post("/apps/{app_id}/revue/valider")
def valider_revue(app_id: str, decision: str = "valider"):
    """Décision humaine sur la proposition (le **garde-fou** avant génération).

    `decision=valider` → statut « validee » (l'incrément peut être lancé) ;
    `decision=rejeter` → statut « rejetee ». Sans revue préalable : 400.
    """
    app_row = _charger_app(app_id)
    rev = app_row.get("revue")
    if not rev or not isinstance(rev, dict):
        raise HTTPException(400, "Aucune revue à valider — lance d'abord POST /revue")
    if decision not in ("valider", "rejeter"):
        raise HTTPException(400, "decision doit être 'valider' ou 'rejeter'")
    rev["statut"] = "validee" if decision == "valider" else "rejetee"
    rev["decide_le"] = datetime.now(timezone.utc).isoformat()
    with _connexion() as conn:
        conn.execute("UPDATE apps SET revue=? WHERE id=?",
                     (json.dumps(rev, ensure_ascii=False), app_id))
        conn.commit()
    return {"app_id": app_id, **rev}


def _oria_cfg_depuis_app(world_id: str | None, salons: list | None) -> dict | None:
    """Reconstruit la config messagerie injectée dans l'app à partir des champs stockés.

    À l'application d'un incrément (S32) on régénère le HTML sans repasser par le
    provisioning Oria : la messagerie existante (world + salons déjà créés) est préservée
    en réinjectant la même config navigateur que `_provisionner_messagerie`.
    """
    if not world_id:
        return None
    return {
        "world_id": world_id,
        "salons": salons or [],
        "oria_api": ORIA_URL_PUBLIQUE,
        "matrix": MATRIX_URL_PUBLIQUE,
        "keycloak": {
            "url": KEYCLOAK_URL_PUBLIQUE,
            "realm": KEYCLOAK_REALM,
            "clientId": ORIA_CLIENT_ID,
        },
    }


@app.post("/apps/{app_id}/revue/appliquer")
async def appliquer_revue(app_id: str):
    """Applique une revue **validée** : régénère l'app enrichie des modules proposés (S32).

    Dernier maillon de la chaîne S31 (**proposer ≠ valider ≠ appliquer**). Refuse si la
    revue n'est pas au statut « validee » (409). Réinjecte les modules proposés dans le
    plan livré, **régénère** l'app (même gabarit, messagerie préservée), met à jour
    `plan` + `html` et trace l'application (`statut: appliquee`). Idempotent et non
    destructif : un module déjà présent n'est pas dupliqué, les dormants ne sont pas
    supprimés. Proposition sans nouveau module → 200 `applique:false` (on n'invente rien).
    """
    with _connexion() as conn:
        row = conn.execute(
            "SELECT audit_id, plan, mode, oria_world_id, oria_salons, revue, langue FROM apps WHERE id=?",
            (app_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "App non trouvée")

    rev = json.loads(row["revue"]) if row["revue"] else None
    if not rev or not isinstance(rev, dict):
        raise HTTPException(400, "Aucune revue — lance d'abord POST /revue")
    if rev.get("statut") != "validee":
        raise HTTPException(
            409, f"Revue non validée (statut : {rev.get('statut')}) — "
                 "valide-la d'abord via POST /revue/valider?decision=valider")

    plan = json.loads(row["plan"]) if row["plan"] else {}
    proposition = rev.get("proposition") or {}

    # Pré-check d'idempotence sans LLM : s'il n'y a aucun nouveau module, on s'arrête avant
    # tout appel (honnêteté + économie).
    _, ajoutes_secs = appliquer.construire_plan_enrichi(plan, proposition)
    if not ajoutes_secs:
        return {"app_id": app_id, "applique": False, "modules_ajoutes": [],
                "raison": "aucun nouveau module à ajouter "
                          "(proposition sans module ou incrément déjà appliqué)"}

    # Schéma fin par module via le LLM (S34), repli générique si Gateway KO.
    langue = normaliser_langue(row["langue"])
    audit = await _charger_audit(row["audit_id"])
    plan_enrichi, ajoutes = await appliquer.construire_plan_enrichi_llm(plan, proposition, audit, langue)
    hebergee = (row["mode"] or "autonome") == "hebergee"
    salons = json.loads(row["oria_salons"]) if row["oria_salons"] else []
    oria_cfg = _oria_cfg_depuis_app(row["oria_world_id"], salons)

    html = generer_html(
        audit, plan_enrichi,
        app_id=(app_id if hebergee else ""),
        api_base=(DONNEES_URL_PUBLIQUE if hebergee else ""),
        oria=oria_cfg, langue=langue,
    )

    rev["statut"] = "appliquee"
    rev["applique_le"] = datetime.now(timezone.utc).isoformat()
    rev["modules_ajoutes"] = ajoutes
    with _connexion() as conn:
        conn.execute("UPDATE apps SET plan=?, html=?, revue=? WHERE id=?",
                     (json.dumps(plan_enrichi, ensure_ascii=False), html,
                      json.dumps(rev, ensure_ascii=False), app_id))
        conn.commit()
    print(f"[generateur] revue {app_id} appliquée : +{len(ajoutes)} module(s) "
          f"({', '.join(a['nom'] for a in ajoutes)})")
    return {"app_id": app_id, "applique": True, "modules_ajoutes": ajoutes,
            "nb_entites_plan": len([e for e in plan_enrichi.get("entites") or []
                                    if isinstance(e, dict)])}


@app.get("/apps/{app_id}/export")
def exporter_app_complet(app_id: str):
    """Renvoie l'app COMPLÈTE (html + plan + refs Oria) pour décrochage (S6).

    Contrairement à `GET /apps/{id}` (qui omet le html), cet export contient tout
    ce qu'il faut pour réinjecter l'app à l'identique lors d'une reprise.
    """
    with _connexion() as conn:
        row = conn.execute("SELECT * FROM apps WHERE id=?", (app_id,)).fetchone()
    if not row:
        raise HTTPException(404, "App non trouvée")
    d = dict(row)
    for champ in ("plan", "oria_salons", "partage_forge", "revue"):
        if d.get(champ):
            try:
                d[champ] = json.loads(d[champ])
            except Exception:
                pass
    return d


@app.post("/apps/import")
def importer_app(payload: dict):
    """Réinsère une app complète (id préservé) — reprise d'un dossier décroché (S6)."""
    def _ser(v):
        if v is None or isinstance(v, str):
            return v
        return json.dumps(v, ensure_ascii=False)

    app_id = payload.get("id") or str(uuid.uuid4())
    partage = payload.get("partage_forge")
    with _connexion() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO apps
               (id, date_creation, audit_id, nom_entreprise, plan, html, statut,
                erreur, mode, oria_world_id, oria_salons, partage_forge)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                app_id,
                payload.get("date_creation") or datetime.now(timezone.utc).isoformat(),
                payload.get("audit_id") or "",
                payload.get("nom_entreprise"),
                _ser(payload.get("plan")),
                payload.get("html") or "",
                payload.get("statut") or "termine",
                payload.get("erreur"),
                payload.get("mode") or "autonome",
                payload.get("oria_world_id"),
                _ser(payload.get("oria_salons")),
                _ser(partage),
            ),
        )
        conn.commit()
    # Reprise (S6) : si l'app décrochée avait un partage consenti actif, on ré-arme le
    # pont (best-effort) — le consentement voyage avec le dossier portable.
    if isinstance(partage, dict) and partage.get("actif"):
        try:
            pont_crm.pousser(app_id, partage)
        except Exception as e:
            print(f"[generateur] ré-armement pont à la reprise échoué ({app_id}) : {e}")
    return {"id": app_id, "statut": "termine"}


@app.get("/apps/{app_id}/html")
def telecharger_html(app_id: str):
    with _connexion() as conn:
        row = conn.execute(
            "SELECT html, nom_entreprise, statut, erreur FROM apps WHERE id=?", (app_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "App non trouvée")
    if row["statut"] == "en_cours":
        raise HTTPException(202, "Génération en cours, réessaie dans quelques secondes")
    if row["statut"] == "erreur":
        raise HTTPException(500, f"Erreur lors de la génération : {row['erreur']}")
    nom = (row["nom_entreprise"] or "app").replace(" ", "_").replace("/", "_").lower()
    return Response(
        content=row["html"],
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nom}_dashboard.html"'},
    )


@app.post("/apps/{app_id}/exporter")
def exporter_app(app_id: str):
    """Écrit l'app sur disque (dossier par entreprise) prête à être remise au client."""
    with _connexion() as conn:
        row = conn.execute(
            "SELECT html, nom_entreprise, statut, date_creation, mode FROM apps WHERE id=?", (app_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "App non trouvée")
    if row["statut"] != "termine":
        raise HTTPException(400, f"L'app n'est pas prête (statut : {row['statut']})")

    nom = row["nom_entreprise"] or "Entreprise"
    hebergee = (row["mode"] or "autonome") == "hebergee"
    dossier = os.path.join(EXPORT_DIR, _slug(nom))
    try:
        os.makedirs(dossier, exist_ok=True)
        chemin_html = os.path.join(dossier, "index.html")
        with open(chemin_html, "w", encoding="utf-8") as f:
            f.write(row["html"])
        if hebergee:
            note_donnees = (
                "Cette application est en mode HÉBERGÉ : les données saisies sont\n"
                "enregistrées sur le serveur (brique « donnees ») et partagées entre tous\n"
                "les utilisateurs. La brique « donnees » doit être démarrée et joignable\n"
                "depuis le navigateur pour que l'application fonctionne.\n"
            )
        else:
            note_donnees = (
                "Cette application est en mode AUTONOME : les données saisies (devis,\n"
                "clients, etc.) sont enregistrées localement dans le navigateur de chaque\n"
                "utilisateur (localStorage), sans serveur.\n"
            )
        lisezmoi = (
            f"Application générée par Workplace pour : {nom}\n"
            f"Date : {row['date_creation']}\n"
            f"Mode : {'hébergé (multi-utilisateur)' if hebergee else 'autonome (mono-poste)'}\n\n"
            "MISE EN PLACE\n"
            "-------------\n"
            "1. Ouvrez index.html dans un navigateur (double-clic), ou\n"
            "2. Hébergez le dossier sur n'importe quel serveur web statique.\n\n"
            + note_donnees
        )
        with open(os.path.join(dossier, "LISEZMOI.txt"), "w", encoding="utf-8") as f:
            f.write(lisezmoi)
    except OSError as e:
        raise HTTPException(500, f"Échec de l'export : {e}")

    return {
        "exporte": True,
        "nom_entreprise": nom,
        "dossier_conteneur": dossier,
        "fichiers": ["index.html", "LISEZMOI.txt"],
        "note": "Dossier monté sur l'hôte dans ~/Desktop/Workplace/apps_exportees/",
    }


class DemandePackage(BaseModel):
    # Ports publiés par le bundle déployé sur la machine du client.
    port_app: int = 8090
    port_donnees: int = 5510
    port_keycloak: int = 8095   # serveur d'identité embarqué (comptes du client)


@app.post("/apps/{app_id}/packager")
def packager_app(app_id: str, demande: DemandePackage | None = None):
    """Produit un bundle Docker reproductible (app + persistance dédiée) — déploiement S4.

    Au-delà de l'export d'un fichier : un dossier autonome lancé d'un `docker compose up`.
    """
    demande = demande or DemandePackage()
    with _connexion() as conn:
        row = conn.execute(
            "SELECT html, nom_entreprise, statut, date_creation, plan FROM apps WHERE id=?",
            (app_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "App non trouvée")
    if row["statut"] != "termine":
        raise HTTPException(400, f"L'app n'est pas prête (statut : {row['statut']})")

    try:
        plan = json.loads(row["plan"]) if row["plan"] else {}
    except Exception:
        plan = {}

    try:
        recap = packager.packager_bundle(
            app_id=app_id,
            nom=row["nom_entreprise"] or "Entreprise",
            html=row["html"],
            plan=plan,
            date=row["date_creation"],
            export_dir=EXPORT_DIR,
            donnees_src=DONNEES_SRC,
            port_app=demande.port_app,
            port_donnees=demande.port_donnees,
            port_keycloak=demande.port_keycloak,
        )
    except FileNotFoundError as e:
        raise HTTPException(500, str(e))
    except Exception as e:
        raise HTTPException(500, f"Échec du packaging : {e}")

    return {
        "package": True,
        "nom_entreprise": row["nom_entreprise"],
        "demarrage": "cd <dossier> && docker compose up -d --build",
        "url_app": f"http://localhost:{recap['port_app']}",
        "note": "Dossier monté sur l'hôte dans ~/Desktop/Workplace/apps_exportees/",
        **recap,
    }


@app.get("/apps/{app_id}/apercu")
def apercu_app(app_id: str):
    """Affiche l'app dans le navigateur (inline, sans téléchargement)."""
    with _connexion() as conn:
        row = conn.execute("SELECT html, statut FROM apps WHERE id=?", (app_id,)).fetchone()
    if not row:
        raise HTTPException(404, "App non trouvée")
    if row["statut"] != "termine":
        raise HTTPException(202, f"Pas prête (statut : {row['statut']})")
    return Response(content=row["html"], media_type="text/html; charset=utf-8")


@app.delete("/apps/{app_id}", status_code=204)
def supprimer_app(app_id: str):
    with _connexion() as conn:
        conn.execute("DELETE FROM apps WHERE id=?", (app_id,))
        conn.commit()


@app.get("/sante")
def sante():
    return {"statut": "ok", "service": "generateur", "version": "0.2.0"}
