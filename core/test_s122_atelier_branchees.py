"""S122 — chaque brique « atelier » est branchée au Cœur comme outil appelable.

Invariant de l'épopée refactor « clarté & maintenabilité » : ajouter ou garder une
brique atelier doit la rendre joignable par l'assistant, soit en DÉCLARATIF (champ
`capacites` du manifest → outils dynamiques, S64), soit par un dispatcher CÂBLÉ en dur
(outils_domaines, S115). Ce test échoue si une brique atelier cesse d'être atteignable —
un filet anti-régression qui ne réclame AUCUN Docker (lecture des manifests +
introspection des specs d'outils). Restaurant exclu (sous-stack à part) ; connexion
exclue (reverse-proxy du pont, pas un outil du LLM).
"""
import os

os.environ.setdefault("VAULT_SECRET", "test")
os.environ.setdefault("GATEWAY_KEY", "test")

import etat        # noqa: E402
import catalogue   # noqa: E402
import outils      # noqa: E402

# Brique atelier → préfixes des outils CÂBLÉS en dur qui la desservent (tuple vide = la
# brique est desservie UNIQUEMENT en déclaratif, via son champ `capacites`).
ATELIER = {
    "mail": (),
    "recherche": (),
    "images": (),
    "telephonie": (),
    "calcul": (),
    "synopsis": (),
    "paiements": (),
    "voix": (),                          # S122 : nouvellement branchée en déclaratif
    "studio": ("studio_",),              # câblé en dur (orchestration + portes de confirmation)
    "personnages": ("personnage_",),     # câblé en dur (atelier holistique)
    "transcription": ("transcription_",),
}

VOIX_ATTENDUES = {"voix_etat", "voix_reglages_lire", "voix_moteur_changer",
                  "voix_clones_lister", "voix_clone_supprimer"}


def _registre():
    etat.registre.charger()
    return etat.registre


def test_chaque_brique_atelier_est_joignable():
    reg = _registre()
    par_brique: dict = {}
    for cap in catalogue.collecter_capacites(reg):
        par_brique.setdefault(cap["brique"], []).append(cap["nom"])
    statiques = outils._NOMS_STATIQUES
    manquantes = []
    for brique, prefixes in ATELIER.items():
        en_declaratif = bool(par_brique.get(brique))
        en_dur = any(n.startswith(p) for p in prefixes for n in statiques)
        if not (en_declaratif or en_dur):
            manquantes.append(brique)
    assert not manquantes, f"Briques atelier non branchées au Cœur : {manquantes}"


def test_voix_expose_ses_capacites_au_llm():
    """La brique voix (S122) doit apparaître comme de VRAIS outils du LLM."""
    reg = _registre()
    noms = {s["function"]["name"] for s in outils.outils_pour(reg)}
    assert VOIX_ATTENDUES <= noms, f"Capacités voix absentes des outils : {VOIX_ATTENDUES - noms}"


def test_voix_capacites_sans_collision_statique():
    """Aucune capacité voix ne doit être masquée par un outil câblé homonyme."""
    assert not (VOIX_ATTENDUES & outils._NOMS_STATIQUES)


def test_voix_actions_passent_la_porte_de_confirmation():
    """Les capacités à effet de bord sont des ACTIONS (gate) ; les lectures n'en sont pas."""
    reg = _registre()
    assert outils.est_action("voix_moteur_changer", reg)
    assert outils.est_action("voix_clone_supprimer", reg)
    assert not outils.est_action("voix_etat", reg)
    assert not outils.est_action("voix_reglages_lire", reg)
    assert not outils.est_action("voix_clones_lister", reg)
