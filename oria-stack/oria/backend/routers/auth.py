import json
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Optional
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import get_db
from models.user import User
from jose import JWTError, jwt

from config import config
from services.auth_service import AuthService, get_auth_service
import services.matrix_service as matrix

from agent_personnel_shared.keycloak_auth import (
    KeycloakSettings,
    verify_token_sync,
)

router = APIRouter()

# Configuration Keycloak partagée. `audience` reflète l'historique Oria (CLIENT_ID).
# Pour passer en mode multi-tenant : vider la variable d'env KEYCLOAK_CLIENT_ID.
_KC = KeycloakSettings(
    url=config.KEYCLOAK_URL,
    realm=config.KEYCLOAK_REALM,
    audience=config.KEYCLOAK_CLIENT_ID,
    jwks_ttl=300,
    extra_decode_options={"verify_at_hash": False},
)

# ─── Multi-realm (S14 — messagerie des apps livrées) ──────────────────────────
# Une app livrée s'authentifie sur SON PROPRE Keycloak (realm `client-<slug>`) et
# réutilise ce jeton pour la messagerie. Oria doit donc accepter, EN PLUS du realm
# central `oria`, les realms des bundles de confiance. Le *contenu* reste cloisonné
# par world/espace (un par entreprise) — seule l'IDENTITÉ devient celle du client.
#
# Allowlist de realms (`KEYCLOAK_REALMS_AUTORISES`, séparés par virgules). Supporte
# un motif suffixe `*` (ex. `client-*`) pour faire confiance à tous les bundles sans
# reconfigurer Oria à chaque livraison (le packager fige la convention `client-<slug>`).
# Le realm central est toujours autorisé.
def _parse_csv(env: str) -> list[str]:
    return [x.strip() for x in os.getenv(env, "").split(",") if x.strip()]


_REALMS_EXACTS = {config.KEYCLOAK_REALM}
_REALMS_PREFIXES: list[str] = []
for _r in _parse_csv("KEYCLOAK_REALMS_AUTORISES"):
    if _r.endswith("*"):
        _REALMS_PREFIXES.append(_r[:-1])
    else:
        _REALMS_EXACTS.add(_r)

# Bases d'émetteurs réseau-joignables autorisées (anti-SSRF) : on ne va JAMAIS
# chercher les JWKS sur un hôte arbitraire tiré d'un `iss` forgé. Défaut : le KC
# central. Pour un bundle dont le Keycloak est sur un autre hôte joignable par Oria,
# ajouter sa base à `KEYCLOAK_ISSUERS_AUTORISES`.
_BASES_AUTORISEES = {config.KEYCLOAK_URL.rstrip("/")} | {
    b.rstrip("/") for b in _parse_csv("KEYCLOAK_ISSUERS_AUTORISES")
}

_kc_par_realm: dict[tuple[str, str], KeycloakSettings] = {}


def _realm_autorise(realm: str) -> bool:
    return bool(realm) and (
        realm in _REALMS_EXACTS or any(realm.startswith(p) for p in _REALMS_PREFIXES)
    )


def _resoudre_kc(token: str) -> KeycloakSettings:
    """Choisit la config Keycloak selon le realm émetteur du jeton (issuer)."""
    try:
        iss = jwt.get_unverified_claims(token).get("iss", "")
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Token illisible: {exc}")
    base, sep, realm = iss.partition("/realms/")
    realm = realm.strip("/")
    if not sep or not _realm_autorise(realm):
        raise HTTPException(status_code=401, detail=f"Realm non autorisé: {realm or '?'}")
    # Realm central → comportement historique (audience oria-app). Realm de bundle →
    # jeton du client `app`, donc pas d'audience oria-app à exiger.
    if realm == config.KEYCLOAK_REALM:
        return _KC
    base = base.rstrip("/")
    # On ne fetch les JWKS que depuis une base de confiance ; sinon repli sur le KC central.
    url = base if base in _BASES_AUTORISEES else config.KEYCLOAK_URL
    cle = (url, realm)
    kc = _kc_par_realm.get(cle)
    if kc is None:
        kc = KeycloakSettings(
            url=url, realm=realm, audience="", jwks_ttl=300,
            extra_decode_options={"verify_at_hash": False},
        )
        _kc_par_realm[cle] = kc
    return kc


def _get_jwks() -> dict:
    """Compat — exposé pour les routers existants (worlds/admin/social)."""
    from agent_personnel_shared.keycloak_auth import _fetch_jwks_sync
    try:
        return _fetch_jwks_sync(_KC)
    except Exception as exc:
        if _KC._jwks_cache is None:
            raise HTTPException(503, f"Keycloak JWKS indisponible: {exc}")
        return _KC._jwks_cache


def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Dépendance FastAPI — valide le Bearer token Keycloak et auto-provisionne l'utilisateur."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token manquant")
    token = auth[7:]
    try:
        payload = verify_token_sync(token, _resoudre_kc(token))
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Token invalide: {exc}")

    keycloak_sub = payload.get("sub")
    if not keycloak_sub:
        raise HTTPException(status_code=401, detail="Token invalide (sub manquant)")

    svc = AuthService(db)
    user = svc.get_user(keycloak_sub)
    if not user:
        user = svc.provision_new_user(keycloak_sub, payload, matrix)

    return {"id": user.id, "nom": user.nom, "avatar_emoji": user.avatar_emoji}


# ─── Modèles Pydantic ────────────────────────────────────────────────────────

class MiseAJourProfil(BaseModel):
    nom: Optional[str] = None
    avatar_emoji: Optional[str] = None
    bio: Optional[str] = None
    is_public: Optional[bool] = None
    documents_partageables_par_defaut: Optional[bool] = None
    # S25 — thème d'apparence. Dict {accent, surface, text, tint} (les 3 premiers
    # = couleurs hex, tint = 0..100). Sanitisé côté serveur avant persistance.
    theme: Optional[dict] = None
    # S40 — langue d'interface (code i18next). Sanitisée contre la liste blanche.
    langue: Optional[str] = None


# ─── Thème d'apparence (S25) ──────────────────────────────────────────────────

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def _sanitize_theme(raw) -> Optional[str]:
    """Valide/normalise un thème en JSON compact. Ne garde que les clés connues ;
    renvoie None si rien d'exploitable (on n'écrase alors pas l'existant)."""
    if not isinstance(raw, dict):
        return None
    out = {}
    for k in ("accent", "surface", "text"):
        v = raw.get(k)
        if isinstance(v, str) and _HEX_RE.match(v.strip()):
            out[k] = v.strip().lower()
    if "tint" in raw:
        try:
            out["tint"] = max(0, min(100, int(raw["tint"])))
        except (TypeError, ValueError):
            pass
    return json.dumps(out, separators=(",", ":")) if out else None


def _theme_to_dict(stored: Optional[str]) -> Optional[dict]:
    if not stored:
        return None
    try:
        d = json.loads(stored)
        return d if isinstance(d, dict) else None
    except (ValueError, TypeError):
        return None


# ─── Langue d'interface (S40) ─────────────────────────────────────────────────

# Liste blanche = exactement les locales livrées avec le front (i18n/locales/*.json).
_LANGUES_OK = {"fr", "en", "es", "ar", "pt", "ja", "zh"}


def _sanitize_langue(raw) -> Optional[str]:
    """Valide un code langue contre la liste blanche. Renvoie None si inconnu
    (on n'écrase alors pas la préférence existante) — repli honnête côté front."""
    if not isinstance(raw, str):
        return None
    code = raw.strip().lower()
    return code if code in _LANGUES_OK else None


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/me")
def get_me(
    user=Depends(get_current_user),
    svc: AuthService = Depends(get_auth_service),
):
    db_user = svc.get_user(user["id"])
    return {
        "user": {
            **user,
            "bio": db_user.bio or "" if db_user else "",
            "is_public": db_user.is_public if db_user else True,
            "documents_partageables_par_defaut": db_user.documents_partageables_par_defaut if db_user else False,
            "theme": _theme_to_dict(db_user.theme if db_user else None),
            "langue": (db_user.langue or None) if db_user else None,
            "setup_completed_at": (
                db_user.setup_completed_at.isoformat()
                if (db_user and db_user.setup_completed_at) else None
            ),
        },
        "matrix_user_id":      db_user.matrix_user_id if db_user else None,
        "matrix_access_token": db_user.matrix_access_token if db_user else None,
    }


@router.post("/logout")
def logout():
    # Le logout effectif se fait côté frontend via keycloak.logout()
    return {"ok": True}


@router.patch("/me")
def update_profil(
    data: MiseAJourProfil,
    user=Depends(get_current_user),
    svc: AuthService = Depends(get_auth_service),
):
    db_user = svc.get_user(user["id"])
    if not db_user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    nom_clean = data.nom.strip() if data.nom is not None else None
    theme_clean = _sanitize_theme(data.theme) if data.theme is not None else None
    langue_clean = _sanitize_langue(data.langue) if data.langue is not None else None
    db_user = svc.update_profile(
        db_user,
        nom=nom_clean,
        avatar_emoji=data.avatar_emoji,
        bio=data.bio,
        is_public=data.is_public,
        documents_partageables_par_defaut=data.documents_partageables_par_defaut,
        theme=theme_clean,
        langue=langue_clean,
    )
    return {
        "user": {
            "id": db_user.id, "nom": db_user.nom, "avatar_emoji": db_user.avatar_emoji,
            "bio": db_user.bio or "", "is_public": db_user.is_public,
            "documents_partageables_par_defaut": db_user.documents_partageables_par_defaut,
            "theme": _theme_to_dict(db_user.theme),
            "langue": db_user.langue or None,
            "setup_completed_at": (
                db_user.setup_completed_at.isoformat() if db_user.setup_completed_at else None
            ),
        }
    }


@router.post("/me/setup-complete")
def mark_setup_complete(
    user=Depends(get_current_user),
    svc: AuthService = Depends(get_auth_service),
):
    db_user = svc.get_user(user["id"])
    if not db_user:
        raise HTTPException(404, "Utilisateur introuvable")
    db_user = svc.mark_setup_completed(db_user)
    return {"setup_completed_at": db_user.setup_completed_at.isoformat()}


@router.delete("/me/setup-complete")
def reset_setup(
    user=Depends(get_current_user),
    svc: AuthService = Depends(get_auth_service),
):
    db_user = svc.get_user(user["id"])
    if not db_user:
        raise HTTPException(404, "Utilisateur introuvable")
    svc.reset_setup(db_user)
    return {"ok": True}


@router.get("/me/2fa-status")
def get_2fa_status(user=Depends(get_current_user)):
    # 2FA géré par Keycloak — toujours False depuis Oria
    return {"totp_enabled": False}


@router.get("/me/export")
def exporter_donnees(
    user=Depends(get_current_user),
    svc: AuthService = Depends(get_auth_service),
):
    """Export RGPD de toutes les données de l'utilisateur."""
    from datetime import datetime, timezone

    db_user = svc.get_user(user["id"])
    if not db_user:
        raise HTTPException(404)

    membres = svc.list_membres_for_user(user["id"])
    return {
        "utilisateur": {
            "id":          db_user.id,
            "email":       db_user.email,
            "nom":         db_user.nom,
            "avatar_emoji": db_user.avatar_emoji,
        },
        "communes":    [{"world_id": m.world_id, "role": m.role} for m in membres],
        "export_date": datetime.now(timezone.utc).isoformat(),
        "note":        "Export RGPD — Article 20 du RGPD — Droit à la portabilité des données",
    }


@router.delete("/me")
def supprimer_compte(
    user=Depends(get_current_user),
    svc: AuthService = Depends(get_auth_service),
):
    """Suppression du compte (droit à l'oubli RGPD)."""
    db_user = svc.get_user(user["id"])
    if not db_user:
        raise HTTPException(404)
    svc.anonymize_account(db_user)
    return {"ok": True, "message": "Compte anonymisé conformément au RGPD"}
