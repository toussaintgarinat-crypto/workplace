"""Compte client auto (S23) — à la livraison, crée le compte d'accès du client.

À la génération d'une app *hébergée + messagerie*, on a déjà provisionné l'espace
Oria (`oria_provisioning`). Ce module ajoute l'**onboarding du client** :

  1. crée (ou retrouve) un **utilisateur Keycloak** dans le realm `oria`, à l'email
     du client — idempotent (recherche par email d'abord) ;
  2. déclenche l'envoi par **Keycloak lui-même** d'un email d'accès via
     `execute-actions-email` (`UPDATE_PASSWORD` + `VERIFY_EMAIL`) → le client reçoit
     un lien « définis ton mot de passe ». **Aucun secret ne circule en clair** ;
  3. **rattache** le client à son espace (world Oria) via `/api/worlds/{id}/rejoindre`
     (user_id = `sub` Keycloak, cohérent avec l'auto-provisioning Oria au 1ᵉʳ login).

Décisions actées (cf. note de prépa) :
  • realm cible = `oria` (SSO central, cohérent avec `oria_provisioning`) ;
  • mot de passe = **lien Keycloak** (option B « recommandée »), pas de mot de passe
    en clair dans l'email.

Tout est **best-effort** : on n'interrompt jamais la livraison si l'onboarding échoue.
Le résultat (statut détaillé) est retourné à l'appelant pour journalisation.

Pré-requis opérationnels (chemin LIVE, cf. doc S23) :
  • le compte de service `workplace-provisioner` doit avoir le rôle
    `realm-management:manage-users` sur le realm `oria` ;
  • le realm `oria` doit avoir un **SMTP configuré** (Mailpit en dev) pour que
    `execute-actions-email` parte réellement.
"""
import os

import httpx

import oria_provisioning as op

# On réutilise la cartographie réseau + l'auth de service d'oria_provisioning.
KEYCLOAK_URL = op.KEYCLOAK_URL
KEYCLOAK_REALM = op.KEYCLOAK_REALM
ORIA_URL_INTERNE = op.ORIA_URL_INTERNE

# Client + redirection de la page « définis ton mot de passe » (atterrit sur Oria).
ORIA_CLIENT_ID = os.getenv("ORIA_CLIENT_ID", "oria-app")
ORIA_REDIRECT_URI = os.getenv("ORIA_URL_PUBLIQUE", "http://localhost:8000")

# Durée de validité du lien d'action (secondes) — 7 jours par défaut.
ACTIONS_LIFESPAN = int(os.getenv("CLIENT_ACTIONS_LIFESPAN", str(7 * 24 * 3600)))


def _admin(c: httpx.Client, email: str, nom: str) -> tuple[str, bool]:
    """Crée (ou retrouve) l'utilisateur Keycloak. Retourne (user_id, cree).

    Idempotent : si un compte existe déjà à cet email, on le réutilise (cree=False).
    """
    base = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users"

    # 1) Déjà présent ?
    r = c.get(base, params={"email": email, "exact": "true"})
    r.raise_for_status()
    existants = r.json()
    if existants:
        return existants[0]["id"], False

    # 2) Création. prénom/nom best-effort depuis le nom de contact fourni.
    prenom, _, nom_famille = (nom or "").partition(" ")
    payload = {
        "username": email,
        "email": email,
        "enabled": True,
        "emailVerified": False,
        "firstName": prenom or email.split("@")[0],
        "lastName": nom_famille or "",
    }
    rc = c.post(base, json=payload)
    if rc.status_code == 409:
        # Course : créé entre-temps → on le retrouve.
        r = c.get(base, params={"email": email, "exact": "true"})
        r.raise_for_status()
        return r.json()[0]["id"], False
    rc.raise_for_status()
    # Keycloak renvoie l'id dans l'en-tête Location: .../users/{id}
    user_id = rc.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
    return user_id, True


def _envoyer_acces(c: httpx.Client, user_id: str) -> None:
    """Demande à Keycloak d'envoyer l'email « définis ton mot de passe »."""
    url = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}/execute-actions-email"
    r = c.put(
        url,
        params={
            "client_id": ORIA_CLIENT_ID,
            "redirect_uri": ORIA_REDIRECT_URI,
            "lifespan": ACTIONS_LIFESPAN,
        },
        json=["UPDATE_PASSWORD", "VERIFY_EMAIL"],
    )
    r.raise_for_status()


def _rejoindre_espace(world_id: str, user_id: str, nom: str) -> None:
    """Inscrit le client comme membre de son world (best-effort).

    L'utilisateur Oria est auto-provisionné au 1ᵉʳ login (`/api/auth/me`, id = sub).
    On pré-enregistre l'appartenance ici ; l'invitation Matrix se fait au login.
    """
    token = op._token()
    with httpx.Client(timeout=15, headers={"Authorization": f"Bearer {token}"}) as c:
        r = c.post(
            f"{ORIA_URL_INTERNE}/api/worlds/{world_id}/rejoindre",
            params={"user_id": user_id, "nom": nom or user_id},
        )
        r.raise_for_status()


def creer_compte_client(email: str, nom_contact: str, world_id: str | None,
                        nom_entreprise: str = "") -> dict:
    """Onboarde le client à la livraison. Best-effort, ne lève jamais.

    Retourne un statut détaillé :
      {ok, compte_cree, email_envoye, rattache_espace, user_id, message}
    """
    statut = {
        "ok": False, "compte_cree": False, "email_envoye": False,
        "rattache_espace": False, "user_id": None, "message": "",
    }
    email = (email or "").strip()
    if not email or "@" not in email:
        statut["message"] = "email client absent ou invalide — onboarding ignoré"
        return statut

    try:
        token = op._token()
    except Exception as e:
        statut["message"] = f"auth Keycloak (provisioner) échouée : {e}"
        return statut

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=20, headers=headers) as c:
            user_id, cree = _admin(c, email, nom_contact)
            statut["user_id"] = user_id
            statut["compte_cree"] = cree
            try:
                _envoyer_acces(c, user_id)
                statut["email_envoye"] = True
            except Exception as e:
                statut["message"] += f" email d'accès non parti ({e});"
                print(f"[client_provisioning] execute-actions-email échoué pour {email} : {e}")
    except Exception as e:
        statut["message"] = f"création/recherche utilisateur échouée : {e}"
        print(f"[client_provisioning] onboarding Keycloak échoué ({email}) : {e}")
        return statut

    # Rattachement à l'espace (best-effort, indépendant de l'email).
    if world_id and statut["user_id"]:
        try:
            _rejoindre_espace(world_id, statut["user_id"], nom_contact or nom_entreprise)
            statut["rattache_espace"] = True
        except Exception as e:
            statut["message"] += f" rattachement espace échoué ({e});"
            print(f"[client_provisioning] /rejoindre échoué (world {world_id}) : {e}")

    statut["ok"] = bool(statut["user_id"])
    if not statut["message"]:
        statut["message"] = (
            "compte créé + email d'accès envoyé" if cree
            else "compte déjà existant + email d'accès renvoyé"
        )
    return statut
