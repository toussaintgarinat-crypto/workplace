"""Filet anti-fuite d'existence (S223) : tout 403 des briques doit être justifié.

## Ce qu'on protège

Un 403 sur une ressource désignée par un identifiant **confirme que cette ressource
existe**. Quand la même route répond 404 pour un identifiant inconnu, l'attaquant distingue
« ressource d'autrui » de « ressource inexistante » — et peut énumérer par balayage ce que
possèdent les autres locataires. La règle (leur ADR-180, « silent blocking ») : **même code,
même corps**, indistinguable de l'extérieur.

L'audit S183 avait vérifié qu'on ne LIT pas les données d'autrui. Il ne vérifiait pas qu'on
ne peut pas DÉDUIRE leur existence du code de retour.

## Comment ce filet marche

On ne peut pas décider automatiquement si un 403 est légitime : « mot de passe incorrect »
l'est, « pas votre commentaire » ne l'est pas. Alors on **inventorie**. Chaque 403 du parc
doit figurer ci-dessous avec sa raison. Un 403 ajouté ou déplacé fait échouer ce test tant
que quelqu'un ne l'a pas classé — ce qui force la question au bon moment plutôt qu'au
prochain audit.

Ajouter une entrée est trivial ; c'est *volontairement* le moment où l'on doit se demander
« est-ce que ce 403 confirme l'existence de quelque chose ? ».
"""

import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
BRIQUES = RACINE / "briques"

# Une ligne compte comme un site 403 si elle porte le code ET un marqueur de réponse HTTP.
# ⚠ On ne peut PAS ancrer le motif sur `HTTPException(403` : la forme multi-ligne
# (`HTTPException(\n    status_code=403,`) passerait à travers — c'est exactement ce que le
# test « justification obsolète » a attrapé à l'écriture de ce filet.
# `\b403\b` seul ne suffit pas : dans `HTTP_403_FORBIDDEN` les underscores sont des
# caractères de mot, donc aucune frontière — la constante nommée passait à travers.
_MOTIF_403 = re.compile(r"\b403\b|HTTP_403_FORBIDDEN")
_MARQUEURS = ("HTTPException", "status_code", "HTTP_403_FORBIDDEN", "JSONResponse")

_EXCLUS = ("/.venv/", "/node_modules/", "/site-packages/", "/__pycache__/",
           "/spearcode/",  # bac à sable de la brique dev : garde-fous de chemin, pas de tenant
           )


def _sans_commentaire(ligne: str) -> str:
    """Retire un commentaire de fin de ligne : les docstrings et commentaires qui
    *parlent* de 403 (« 403 et pas 422 : … ») ne sont pas des sites 403."""
    hors_chaine, guillemet = [], None
    for c in ligne:
        if guillemet:
            if c == guillemet:
                guillemet = None
        elif c in "\"'":
            guillemet = c
        elif c == "#":
            break
        hors_chaine.append(c)
    return "".join(hors_chaine)


def _pertinent(chemin: Path) -> bool:
    p = str(chemin)
    if any(x in p for x in _EXCLUS):
        return False
    return not chemin.name.startswith("test_")


# Inventaire : (chemin relatif, ligne source normalisée) → pourquoi ce 403 ne fuite rien.
# La ligne sert de clé : la MODIFIER refait passer par cette revue, ce qui est le but.
JUSTIFIES: dict[tuple[str, str], str] = {
    # — Authentification / autorisation sans objet désigné : rien à révéler —
    ("briques/restaurant/main.py", 'raise HTTPException(403, "Compte appelant inconnu.")'):
        "porte sur l'appelant, pas sur une ressource ciblée",
    ("briques/restaurant/main.py", 'raise HTTPException(403, "Ancien mot de passe incorrect.")'):
        "l'utilisateur est déjà authentifié sur son propre compte",
    ("briques/restaurant/main.py",
     'raise HTTPException(403, "Rejoignez la table avec le code pour continuer.")'):
        "invite à fournir un code ; ne dit rien de l'existence d'une table précise",
    ("briques/restaurant/main.py", 'raise HTTPException(403, "Code incorrect.")'):
        "réponse identique que la table existe ou non",
    ("briques/transferts/main.py", 'raise HTTPException(403, "En-tête X-Upload-Token manquant.")'):
        "en-tête absent : la requête n'a pas encore désigné de ressource",
    ("briques/connexion/main.py", 'raise HTTPException(403, "Vérification d\'abonnement refusée.")'):
        "porte sur l'appelant",
    ("briques/agenda/backend/auth.py",
     'raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")'):
        "rôle de l'appelant, indépendant de toute ressource",
    ("briques/agenda/backend/routers/digests.py", 'raise HTTPException(403, "Clé digest invalide.")'):
        "clé partagée invalide ; aucune ressource désignée",

    # — Garde-fous techniques (SSRF, chemins) : pas de notion de locataire —
    ("briques/ingestion/main.py",
     'raise HTTPException(status_code=403, detail=f"URL refusée : {e}")'):
        "garde SSRF (S211) : refuse une CIBLE réseau, pas une ressource d'un autre compte",
    ("briques/dev/main.py", "status_code=403,"):
        "brique sensible non débloquée : la liste des briques est publique de toute façon",

    # — Rôle insuffisant SUR une ressource dont l'accès est DÉJÀ établi —
    ("briques/memoire/memory/backend/app/dependencies.py",
     'raise HTTPException(status_code=403, detail=f"Requires one of: {[r.value for r in roles]}")'):
        "l'appelant est déjà membre de l'espace : son existence ne lui apprend rien",
    ("briques/forge/forge/core/app/routers/organizations.py",
     'raise HTTPException(status_code=403, detail="Forbidden")'):
        "appelant déjà membre de l'organisation (rôle insuffisant), ou non-membre traité "
        "en 404 plus haut — les deux chemins ne se distinguent pas",
    ("briques/forge/forge/core/app/routers/sessions.py",
     'raise HTTPException(status_code=403, detail="Forbidden")'):
        "filtre de LISTE par pôle/venture : un pôle inexistant et un pôle d'autrui "
        "échouent tous deux sur le test d'appartenance, même code",
}


def _sites_403() -> list[tuple[str, str, int]]:
    """(chemin relatif, ligne normalisée, numéro de ligne) de chaque 403 du parc."""
    sites = []
    for fichier in sorted(BRIQUES.rglob("*.py")):
        if not _pertinent(fichier):
            continue
        try:
            lignes = fichier.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for n, ligne in enumerate(lignes, 1):
            code = _sans_commentaire(ligne)
            if _MOTIF_403.search(code) and any(m in code for m in _MARQUEURS):
                rel = str(fichier.relative_to(RACINE))
                sites.append((rel, ligne.strip(), n))
    return sites


def test_le_parc_contient_bien_des_403_a_verifier():
    """Garde-fou du garde-fou : si le scan ne trouve plus rien, c'est le scan qui est
    cassé, pas le parc qui est devenu parfait."""
    assert len(_sites_403()) >= 10


@pytest.mark.parametrize("rel,ligne,numero",
                         _sites_403(),
                         ids=lambda v: v if isinstance(v, str) else str(v))
def test_chaque_403_est_justifie(rel, ligne, numero):
    assert (rel, ligne) in JUSTIFIES, (
        f"\n{rel}:{numero} renvoie un 403 non inventorié :\n    {ligne}\n\n"
        "Si ce 403 porte sur une ressource désignée par un identifiant et que la même route "
        "répond 404 quand l'identifiant est inconnu, il FUIT l'existence de la ressource "
        "d'autrui → renvoie 404 à la place.\n"
        "Sinon, ajoute-le à JUSTIFIES dans tests/test_fuite_existence.py avec la raison.")


def test_aucune_justification_devenue_obsolete():
    """Une entrée de l'inventaire qui ne correspond plus à aucun 403 réel doit être
    retirée — sinon l'inventaire se transforme lentement en décor."""
    reels = {(rel, ligne) for rel, ligne, _ in _sites_403()}
    orphelines = sorted(set(JUSTIFIES) - reels)
    assert not orphelines, (
        "entrées de JUSTIFIES qui ne correspondent à aucun 403 du parc "
        f"(code corrigé ? ligne modifiée ?) : {orphelines}")
