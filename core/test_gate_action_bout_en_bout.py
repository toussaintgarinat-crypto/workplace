"""Le gate d'action, prouvé DANS la boucle d'inférence (S222).

`test_accord_action.py` prouve le registre ; ici on prouve le CÂBLAGE — c'est là que le trou
vivait. Le scénario clé est `test_le_llm_ne_peut_pas_se_confirmer_tout_seul` : le faux LLM
appelle une action avec `confirme=true` sans que l'utilisateur ait jamais rien accepté, et on
vérifie que `outils.executer` n'est **jamais** atteint.

Offline, calqué sur test_fil_activite : doublures de `llm_pipeline.completer_flux` et
`outils.executer`.
"""
import asyncio
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
os.environ["STREAM_ACTIF"] = "1"
sys.path.insert(0, os.path.dirname(__file__))

import accord_action  # noqa: E402
import assistant  # noqa: E402
import llm_pipeline  # noqa: E402
import outils  # noqa: E402


class _FauxRegistre:
    def __init__(self, briques):
        self.briques = briques


REGISTRE = _FauxRegistre({
    "mail": {"nom": "mail", "port": 6030, "capacites": [
        {"nom": "mail_envoyer", "chemin": "/envoyer", "methode": "POST", "action": True,
         "description": "Envoie un mail.",
         "params": {"destinataire": {"type": "string", "requis": True}}},
        {"nom": "mail_lister", "chemin": "/mail", "description": "Liste les mails."},
    ]},
})

ARGS_JSON = '{"destinataire": "alice@exemple.fr"}'
ARGS_CONFIRME = '{"destinataire": "alice@exemple.fr", "confirme": true}'


def _jouer(appels, fil="fil-test", message="vas-y"):
    """Joue une conversation où le LLM émet `appels` (liste de (nom, arguments JSON))
    puis répond en texte. Renvoie (évènements, noms réellement exécutés)."""
    executes: list[str] = []
    tours = [
        [{"type": "fin", "message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": f"c{i}", "type": "function",
             "function": {"name": nom, "arguments": args}}
            for i, (nom, args) in enumerate(appels)]}}],
        [{"type": "fin", "message": {"role": "assistant", "content": "Fait."}}],
    ]

    async def faux_flux(*a, **k):
        for evt in tours.pop(0):
            yield evt

    async def faux_exec(nom, args, registre):
        executes.append(nom)
        return '{"ok": true}'

    async def _run():
        return [evt async for evt in assistant.converser(
            [{"role": "user", "content": message}], REGISTRE, fil=fil)]

    a_flux, a_exec = llm_pipeline.completer_flux, outils.executer
    llm_pipeline.completer_flux, outils.executer = faux_flux, faux_exec
    try:
        return asyncio.run(_run()), executes
    finally:
        llm_pipeline.completer_flux, outils.executer = a_flux, a_exec


def _resultat(evts, nom):
    return next(e for e in evts if e["type"] == "resultat_outil" and e["nom"] == nom)


def setup_function():
    accord_action.REGISTRE._demandes.clear()
    accord_action.REGISTRE._lectures.clear()


# ── Le trou d'avant S222 ─────────────────────────────────────────────────────

def test_le_llm_ne_peut_pas_se_confirmer_tout_seul():
    """AVANT S222 ce scénario envoyait vraiment le mail : rien ne vérifiait que l'humain
    avait vu passer la question."""
    evts, executes = _jouer([("mail_envoyer", ARGS_CONFIRME)])
    assert executes == [], "l'action a été exécutée sans accord humain"
    res = _resultat(evts, "mail_envoyer")
    assert "[GATE]" in res["resultat"]
    assert res["confirmation"] is True  # le drapeau SSE et les boutons S76 survivent


def test_demander_puis_confirmer_dans_le_meme_tour_ne_passe_pas():
    """Le LLM joue les deux rôles d'affilée, sans que l'utilisateur ait parlé entre-temps."""
    _, executes = _jouer([("mail_envoyer", ARGS_JSON), ("mail_envoyer", ARGS_CONFIRME)])
    assert executes == ["mail_envoyer"]  # seul l'appel SANS confirme est parti (la demande)


# ── Le parcours légitime reste possible ──────────────────────────────────────

def test_le_parcours_normal_fonctionne_toujours():
    """Tour 1 : le LLM demande. Message utilisateur. Tour 2 : il confirme → ça part."""
    _, executes = _jouer([("mail_envoyer", ARGS_JSON)])
    assert executes == ["mail_envoyer"]

    accord_action.REGISTRE.tour_utilisateur("fil-test", "oui vas-y")

    _, executes = _jouer([("mail_envoyer", ARGS_CONFIRME)])
    assert executes == ["mail_envoyer"], "l'accord humain n'a pas été honoré"


def test_un_refus_de_l_utilisateur_bloque_l_action():
    _jouer([("mail_envoyer", ARGS_JSON)])
    accord_action.REGISTRE.tour_utilisateur("fil-test", "non, annule")
    _, executes = _jouer([("mail_envoyer", ARGS_CONFIRME)])
    assert executes == []


def test_l_accord_ne_couvre_pas_un_autre_destinataire():
    """L'utilisateur accepte pour Alice ; le LLM tente Bob avec le même accord."""
    _jouer([("mail_envoyer", ARGS_JSON)])
    accord_action.REGISTRE.tour_utilisateur("fil-test", "oui")
    _, executes = _jouer([("mail_envoyer", '{"destinataire": "bob@exemple.fr", '
                                           '"confirme": true}')])
    assert executes == []


# ── Aucune régression sur les lectures ───────────────────────────────────────

def test_une_lecture_n_est_jamais_gatee():
    _, executes = _jouer([("mail_lister", "{}")])
    assert executes == ["mail_lister"]


def test_sans_fil_aucune_action_confirmee_ne_passe():
    """Un appelant sans tour de parole humain (co-agent, script) ne peut pas déclencher
    une action confirmée : `fil` absent = aucun accord possible."""
    executes: list[str] = []
    tours = [
        [{"type": "fin", "message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "mail_envoyer", "arguments": ARGS_CONFIRME}}]}}],
        [{"type": "fin", "message": {"role": "assistant", "content": "Fait."}}],
    ]

    async def faux_flux(*a, **k):
        for evt in tours.pop(0):
            yield evt

    async def faux_exec(nom, args, registre):
        executes.append(nom)
        return '{"ok": true}'

    async def _run():
        return [evt async for evt in assistant.converser(
            [{"role": "user", "content": "envoie"}], REGISTRE)]  # pas de `fil`

    a_flux, a_exec = llm_pipeline.completer_flux, outils.executer
    llm_pipeline.completer_flux, outils.executer = faux_flux, faux_exec
    try:
        asyncio.run(_run())
    finally:
        llm_pipeline.completer_flux, outils.executer = a_flux, a_exec
    assert executes == []


# ── S221 dans la même boucle ─────────────────────────────────────────────────

def test_un_argument_requis_manquant_est_refuse_avant_le_reseau():
    """S221 : `outils.executer` n'est jamais atteint quand le manifeste n'est pas respecté."""
    _, executes = _jouer([("mail_envoyer", "{}")])
    assert executes == []
