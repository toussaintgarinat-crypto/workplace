"""Filet de non-régression : des demandes COURTES ou ambiguës doivent garder le bon outil.

Incident Telegram 2026-11-24 : « Retente le résumer » laissait `video_resumer` hors du top_k
(embeddings anglophones) → l'assistant répondait « je n'ai pas d'outil ». Ici on rejoue ce type de
message contre le VRAI catalogue (manifestes du dépôt + outils câblés) dans le PIRE cas : un
embedding totalement inutile (aucune similarité). Ne reste alors que le rattrapage lexical et les
outils récents — c'est le filet qu'on veut garantir, sans réseau ni Gateway.

Limites connues : voir les tests `xfail(strict=True)` en bas. Quand l'un d'eux se met à passer,
pytest échoue (XPASS strict) : c'est le signal pour le retirer de la liste des limites.

$ cd core && python3 -m pytest test_routage_demandes_courtes.py -v
"""
import glob
import json
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

import pytest  # noqa: E402

import outils  # noqa: E402
import routage_outils as r  # noqa: E402


def _catalogue():
    specs = list(outils.OUTILS)
    racine = os.path.join(os.path.dirname(__file__), "..", "briques")
    for m in sorted(glob.glob(os.path.join(racine, "*", "manifest.json"))):
        for c in json.load(open(m)).get("capacites", []):
            specs.append({"type": "function", "function": {
                "name": c["nom"], "description": c.get("description", "")}})
    return specs


CATALOGUE = _catalogue()


def _gardes(message, historique=None):
    """Outils gardés dans le pire cas : embedding sans aucune similarité (index vide)."""
    r.reinitialiser()
    msgs = list(historique or []) + [{"role": "user", "content": message}]
    requete = r.requete_depuis_messages(msgs)
    gardes = r.selectionner([0.0, 1.0], CATALOGUE, top_k=r.TOP_K,
                            toujours=r.outils_recents(msgs), requete=requete)
    return {s["function"]["name"] for s in gardes}


def test_le_catalogue_est_bien_charge():
    assert len(CATALOGUE) > 250
    noms = {s["function"]["name"] for s in CATALOGUE}
    assert {"video_resumer", "image_generer", "agenda_consulter"} <= noms


# ── Demandes que le rattrapage lexical DOIT résoudre ─────────────────────────────────────────

@pytest.mark.parametrize("message, attendu", [
    ("https://youtu.be/MYVQ19hAqWk?is=abc Retente le résumer", "video_resumer"),   # l'incident
    ("Retente le résumer", "video_resumer"),
    ("résume cette vidéo", "video_resumer"),
    ("Peux-tu résumer cette vidéo YouTube ?", "video_resumer"),
    ("génère une image de chat", "image_generer"),
    ("crée une vidéo teaser", "video_teaser"),
    ("transcris cet audio", "transcription_depuis_url"),
    ("résume mes mails", "mail_resumer"),
    ("compose un mail", "mail_composer"),
    ("lance un audit", "audit_lancer"),
    ("recherche web sur les harnais", "recherche_web"),
    ("exporte en pdf", "export_pdf"),
    ("Ajoute du lait", "courses_ajouter"),        # « ajoute » ~ « ajouter » (même radical)
])
def test_demande_courte_garde_le_bon_outil(message, attendu):
    assert attendu in _gardes(message)


def test_un_suivi_trop_court_retrouve_l_outil_du_tour_precedent():
    """« Avec synopsis » ne contient aucun mot du nom `video_resumer` : seul l'historique le sauve."""
    histo = [
        {"role": "user", "content": "résume https://youtu.be/x"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"function": {"name": "video_resumer", "arguments": "{}"}}]},
        {"role": "tool", "name": "video_resumer", "content": "{}"},
        {"role": "assistant", "content": "Voilà."},
    ]
    assert "video_resumer" in _gardes("Avec synopsis", histo)
    assert "video_resumer" not in _gardes("Avec synopsis")        # sans historique : rien


# ── Le rattrapage ne doit jamais inonder la liste ────────────────────────────────────────────

@pytest.mark.parametrize("message", [
    "Retente", "oui", "ok vas-y", "merci", "Quel temps demain ?", "crée", "liste", "lis",
    "résume", "génère", "envoie", "supprime tout", "agenda", "mail", "video",
])
def test_le_rattrapage_reste_borne(message):
    r.reinitialiser()
    extras = r._lexicaux(message, [s["function"]["name"] for s in CATALOGUE])
    assert len(extras) <= r.MAX_LEXICAL


def test_un_mot_banal_n_amene_rien():
    noms = [s["function"]["name"] for s in CATALOGUE]
    assert r._lexicaux("liste", noms) == set() or len(r._lexicaux("liste", noms)) <= r.MAX_LEXICAL
    assert r._lexicaux("oui ok merci", noms) == set()


# ── Limites CONNUES (documentées, pas masquées) ──────────────────────────────────────────────
# Ces demandes ne contiennent aucun mot du NOM de l'outil : seul un bon embedding (ou une
# correspondance sur la description / le nom de la brique) les résoudrait. strict=True : si
# elles passent un jour, ce test casse et on retire la limite d'ici.

@pytest.mark.xfail(strict=True, reason="« rendez-vous » ≠ « agenda_consulter » : embedding requis")
def test_limite_rendez_vous():
    assert "agenda_consulter" in _gardes("Quels sont mes rendez-vous demain ?")


@pytest.mark.xfail(strict=True, reason="« prévu cette semaine » : aucun mot du nom d'outil ; "
                                       "embedding requis")
def test_limite_paraphrase_sans_mot_commun():
    assert "agenda_consulter" in _gardes("Qu'est-ce que j'ai de prévu cette semaine ?")


@pytest.mark.xfail(strict=True, reason="nom de BRIQUE (synopsis) ≠ nom d'outil : non indexé ici")
def test_limite_nom_de_brique_seul():
    assert "video_resumer" in _gardes("Avec synopsis")
