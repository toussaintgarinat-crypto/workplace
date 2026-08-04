"""Routes d'authentification du Cœur (S171) — login/callback/logout OIDC PKCE contre le
realm Keycloak `forge`, client `assistant-app` (déjà déclaré, jamais câblé avant S171)."""

from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import auth
import checkpoint_session
import session_registre

router = APIRouter(tags=["auth"])


def _next_sur(brut: str | None) -> str:
    """Destination post-login SÛRE : chemin interne uniquement (commence par un seul `/`,
    jamais `//` ni `/\\` — anti open-redirect). Sinon défaut `/dashboard` (S182b)."""
    if brut and brut.startswith("/") and not brut.startswith("//") and not brut.startswith("/\\"):
        return brut
    return "/dashboard"


def _page_arret_reprise(next_sur: str) -> HTMLResponse:
    """Page d'arrêt minimaliste (Important 3, revue finale whole-branch) — casse le
    ping-pong d'éviction : sans elle, l'appareil évincé se reconnecte AUTOMATIQUEMENT via
    la session SSO Keycloak encore active (ce n'est pas un logout, `auth_logout` n'a pas été
    appelé côté ancien appareil) et évince à son tour l'appareil qui vient de l'évincer —
    boucle indéfinie entre les deux, chacun rechargeant sa page à tour de rôle. Le lien
    ci-dessous relance le VRAI flux Keycloak seulement sur un clic explicite de l'humain
    (`reprise_confirmee=1`, jamais posé automatiquement par ce serveur)."""
    lien = f"/auth/login?next={urllib.parse.quote(next_sur, safe='')}&reprise_confirmee=1"
    html = f"""<!doctype html>
<html lang="fr">
<head><meta charset="utf-8"><title>Session reprise sur un autre appareil</title></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 32rem;
             margin: 15vh auto; text-align: center; padding: 0 1rem;">
  <p>Ce compte est utilisé sur un autre appareil.</p>
  <p><a href="{lien}">Reprendre la main ici</a></p>
</body>
</html>"""
    return HTMLResponse(html)


@router.get("/auth/login")
async def auth_login(request: Request):
    next_sur = _next_sur(request.query_params.get("next"))
    if (
        "motif=reprise_ailleurs" in next_sur
        and request.cookies.get(auth.COOKIE_SESSION) is not None
        and request.query_params.get("reprise_confirmee") != "1"
    ):
        # Éviction détectée (cf. core/auth.py::exiger_session/sub_session_optionnel) ET un
        # cookie de session (même périmé) est encore présent : NE PAS enchaîner
        # automatiquement sur Keycloak, cf. `_page_arret_reprise`.
        return _page_arret_reprise(next_sur)

    verifier, challenge = auth.generer_pkce()
    state = auth.jeton_aleatoire()
    redirect_uri = str(request.url_for("auth_callback"))
    pending = auth.chiffrer_cookie({
        "code_verifier": verifier,
        "state": state,
        "redirect_uri": redirect_uri,
        # Destination après login (ex. accepter une invitation d'agenda) ; déjà validée
        # ci-dessus (next_sur).
        "next": next_sur,
    })

    params = {
        "client_id": auth.KEYCLOAK_CLIENT_ID,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = (
        f"{auth.KEYCLOAK_PUBLIC_URL}/realms/{auth.KEYCLOAK_REALM}/protocol/openid-connect/auth"
        f"?{urllib.parse.urlencode(params)}"
    )
    resp = RedirectResponse(url, status_code=307)
    resp.set_cookie(
        auth.COOKIE_PENDING, pending,
        httponly=True, secure=auth.AUTH_COOKIE_SECURE, samesite="lax",
        max_age=auth.PENDING_COOKIE_MAX_AGE,
    )
    return resp


@router.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request, code: str, state: str):
    pending = auth.dechiffrer_cookie(request.cookies.get(auth.COOKIE_PENDING))
    if pending is None or pending.get("state") != state:
        raise HTTPException(status_code=400, detail="Requête d'authentification invalide ou expirée")

    try:
        tokens = await auth.echanger_code(code, pending["code_verifier"], pending["redirect_uri"])
        payload = await auth.verify_token(tokens["access_token"], auth.KC)
        sub = payload["sub"]
        refresh_token = tokens["refresh_token"]
    except Exception:
        # Code expiré/déjà utilisé (retour arrière, double-soumission), Keycloak
        # injoignable, JWT invalide, ou réponse/JWT de forme inattendue (clé manquante) :
        # jamais de 500 nu sur ce chemin facilement atteignable (spec S171, cf.
        # `exiger_session` dans core/auth.py qui suit déjà exactement ce motif) — on
        # renvoie vers le point d'entrée normal plutôt que de laisser fuiter l'exception.
        return RedirectResponse("/auth/login", status_code=303)

    appareil = request.headers.get("user-agent", "inconnu")[:200]
    nouvelle_generation, ancienne = session_registre.nouvelle_session(sub, appareil)
    if ancienne is not None:
        # Une session existait déjà pour ce compte : on la considère comme évincée par
        # celle-ci. Le point de contrôle VISE À s'assurer qu'aucune écriture en attente côté
        # ancien appareil n'est perdue avant que sa prochaine requête ne le déconnecte (cf.
        # core/auth.py::exiger_session/sub_session_optionnel, qui comparent la génération à
        # chaque appel) — c'est un stub aujourd'hui (cf. checkpoint_session.py), et même une
        # fois branché sur une vraie réplication, il ne couvrira pas la fenêtre d'écriture
        # APRÈS ce point tant que l'ancien appareil n'a pas fait sa prochaine requête
        # protégée (découverte différée, pas éviction nette — détail dans
        # checkpoint_session.py, Important 5).
        checkpoint_session.declencher_checkpoint(sub)

    session = {
        "sub": sub,
        "nom": payload.get("nom"),
        "avatarEmoji": payload.get("avatarEmoji"),
        "refresh_token": refresh_token,
        "generation": nouvelle_generation,
        # Identifiant de CETTE instance du registre (Important 6, revue finale
        # whole-branch) — détecte une perte du volume core_data : sans lui, un registre
        # neuf reparti à generation=1 rendrait valide un cookie évincé portant justement
        # generation=1 (cas majoritaire), par coïncidence numérique.
        "registre_id": session_registre.identifiant_registre(),
    }
    resp = RedirectResponse(_next_sur(pending.get("next")), status_code=307)
    resp.set_cookie(
        auth.COOKIE_SESSION, auth.chiffrer_cookie(session),
        httponly=True, secure=auth.AUTH_COOKIE_SECURE, samesite="lax",
        max_age=auth.SESSION_COOKIE_MAX_AGE,
    )
    resp.delete_cookie(auth.COOKIE_PENDING)
    return resp


@router.get("/auth/logout")
async def auth_logout(request: Request):
    """Détruit le cookie de session local ET la session SSO Keycloak (RP-Initiated Logout) —
    sans ça, la prochaine visite de /auth/login relogue silencieusement via la session SSO
    encore active côté Keycloak, donnant l'impression que le bouton « Déconnexion » ne fait
    rien. GET (navigation, pas fetch) : la chaîne de redirections traverse Keycloak, une
    autre origine que le Cœur — un fetch() la suivrait et se ferait bloquer par CORS.

    Purge aussi l'entrée du registre de session (Important 4, revue finale whole-branch) —
    sans ça, un logout propre suivi d'une reconnexion normale (même appareil ou un autre)
    déclenchait quand même un checkpoint fantôme : le registre croyait encore une session
    active pour ce compte alors qu'elle venait d'être fermée proprement ici."""
    sub = auth.sub_session_optionnel(request)
    if sub:
        session_registre.fermer_session(sub)

    params = {
        "client_id": auth.KEYCLOAK_CLIENT_ID,
        "post_logout_redirect_uri": str(request.url_for("auth_login")),
    }
    url = (
        f"{auth.KEYCLOAK_PUBLIC_URL}/realms/{auth.KEYCLOAK_REALM}/protocol/openid-connect/logout"
        f"?{urllib.parse.urlencode(params)}"
    )
    resp = RedirectResponse(url, status_code=303)
    resp.delete_cookie(auth.COOKIE_SESSION)
    return resp
