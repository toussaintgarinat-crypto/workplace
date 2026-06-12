"""Briefing quotidien — le Jarvis parle le premier (Sprint S30).

Chaque matin, l'assistant VIENT vers l'utilisateur : rendez-vous du jour,
factures impayées approchant J+7/15/30, état du pipeline commercial, et coût LLM
de la veille. Les faits sont collectés auprès des briques existantes (agenda S10,
Forge relances/CRM S20/S22, journal d'usage S138), puis **synthétisés** en un
court message par l'**économe local** (la cascade cost-first de l'assistant met
un modèle gratuit en tête → coût ~0, S138). Le briefing est déposé comme un
**rappel proactif** → il s'affiche dans la pastille 🔔 existante (S12), sans
nouveau canal ni nouvelle table.

Déclenchement : par l'**horloge** (S29). Le noyau déclare une tâche
`briefing-quotidien` (cadence 24 h) dans `briques/noyau/manifest.json` ; l'horloge
l'appelle via `POST /briefing/executer` exactement comme n'importe quel contrat
de brique — ce qui prouve la dépendance S29→S30 de bout en bout, sans cas
particulier dans le planificateur.

Deux garde-fous fidèles au reste de `core/` :
  • **idempotent par jour** : un seul briefing par date (clé `briefing:AAAA-MM-JJ`),
    même s'il a déjà été lu (cf. `proactif.existe_cle`) ;
  • **tolérant** : chaque source qui échoue est notée `indisponible` sans casser
    le briefing — le Jarvis dit ce qu'il sait, jamais une stacktrace.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

import agenda
import config_assistant
import journal_usage
import langue as langue_mod
import llm_pipeline
import orchestrateur
import proactif

logger = logging.getLogger(__name__)

FUSEAU = "Europe/Paris"

def prompt_briefing(langue=None) -> str:
    """Prompt système du briefing, rédigé dans la langue du Jarvis (S39, défaut `fr`)."""
    return (
        "Tu es le Jarvis de Workplace. Rédige le BRIEFING DU MATIN de l'utilisateur, "
        f"{langue_mod.consigne_resume(langue)}, chaleureux et concret, ~120 mots maximum. "
        "À partir des FAITS fournis (au format JSON), couvre dans cet ordre et SEULEMENT "
        "si pertinent : les rendez-vous du jour, les factures à relancer (impayés "
        "J+7/15/30), l'état du pipeline commercial, et le coût LLM de la veille. Mets en "
        "avant ce qui demande une action. N'invente RIEN : si une source porte le champ "
        "`indisponible`, ignore-la silencieusement. Si la journée est calme, dis-le "
        "simplement. Commence directement par le contenu (pas de « Voici votre briefing »)."
    )


# ── Heure locale ─────────────────────────────────────────────────────────────

def _aujourdhui() -> datetime:
    try:
        return datetime.now(ZoneInfo(FUSEAU))
    except Exception:  # noqa: BLE001 — fuseau absent : on retombe sur l'heure système
        return datetime.now()


# ── Collecte des faits (chaque source tolère l'échec) ────────────────────────

async def _faits_agenda(registre, jour: datetime) -> dict:
    """Rendez-vous d'aujourd'hui, du début à la fin de la journée locale."""
    debut = jour.replace(hour=0, minute=0, second=0, microsecond=0)
    fin = debut + timedelta(days=1)
    try:
        evts = await agenda.lister_evenements(registre, debut.isoformat(), fin.isoformat())
        rdv = [{"heure": (e.get("start_at") or "")[11:16],
                "titre": e.get("title") or "(sans titre)",
                "lieu": e.get("location") or None} for e in evts]
        return {"nombre": len(rdv), "rendez_vous": rdv}
    except Exception as ex:  # noqa: BLE001
        logger.warning("Briefing/agenda : %s", ex)
        return {"indisponible": str(ex)}


async def _faits_forge(client: httpx.AsyncClient, registre, chemin: str) -> dict:
    """Appel LECTURE SEULE d'un contrat Forge (relances/apercu, crm). L'auth S2S
    est gérée *dans* l'adaptateur Forge ; ici on ne fait qu'un GET tolérant."""
    try:
        base = orchestrateur._brique_base(registre, "forge")
    except RuntimeError as ex:
        return {"indisponible": str(ex)}
    try:
        r = await client.get(f"{base}{chemin}", timeout=30)
    except httpx.HTTPError as ex:
        return {"indisponible": f"Forge injoignable : {ex}"}
    if r.status_code >= 400:
        return {"indisponible": f"HTTP {r.status_code}"}
    try:
        return r.json()
    except ValueError:
        return {"indisponible": "réponse Forge illisible"}


def _resume_pipeline(crm: dict) -> dict:
    """Réduit la réponse `/crm` au strict utile pour le briefing (pas la liste
    complète des prospects, qui gonflerait le prompt) : total + récap pipeline."""
    if "indisponible" in crm:
        return crm
    return {"total_prospects": crm.get("total", 0),
            "pipeline": crm.get("pipeline", {})}


def _faits_cout_veille(jour: datetime) -> dict:
    """Coût LLM agrégé de la veille (journal d'usage S138, dates UTC). Approx.
    journalière suffisante pour une ligne de briefing — pas de la comptabilité."""
    veille = (jour - timedelta(days=1)).strftime("%Y-%m-%d")
    return {"date": veille, **journal_usage.agregat_jour(veille)}


async def collecter(registre, *, jour: datetime | None = None) -> dict:
    """Rassemble les quatre sources du briefing en parallèle. Ne lève jamais :
    une source en panne devient `{"indisponible": …}`."""
    jour = jour or _aujourdhui()
    async with httpx.AsyncClient(timeout=30) as client:
        agenda_f, impayes, crm = await asyncio.gather(
            _faits_agenda(registre, jour),
            _faits_forge(client, registre, "/relances/apercu"),
            _faits_forge(client, registre, "/crm"),
        )
    return {
        "date": jour.strftime("%Y-%m-%d"),
        "jour_semaine": jour.strftime("%A"),
        "agenda": agenda_f,
        "impayes": impayes,
        "pipeline": _resume_pipeline(crm),
        "cout_llm_veille": _faits_cout_veille(jour),
    }


# ── Synthèse par l'économe local ─────────────────────────────────────────────

async def rediger(faits: dict, conf: dict | None = None) -> llm_pipeline.Resultat:
    """Rédige le briefing à partir des faits, via la cascade cost-first (modèle
    gratuit en tête → coût ~0). Un seul appel LLM, étiqueté `briefing` au journal."""
    conf = conf or config_assistant.charger()
    modeles = await config_assistant.chaine_modeles(conf)
    if not modeles:  # garde-fou : ne jamais partir sans modèle
        modeles = [conf.get("repli_payant") or config_assistant.DEFAUT_REPLI_PAYANT]
    messages = [
        {"role": "system", "content": prompt_briefing(conf.get("langue"))},
        {"role": "user", "content": "FAITS (JSON) :\n"
         + json.dumps(faits, ensure_ascii=False)},
    ]
    return await llm_pipeline.completer(
        messages, modeles=modeles, tools=None, temperature=0.3, max_tokens=400,
        etiquette="briefing", conf=conf, trim_contexte=False,
    )


# ── Orchestration : collecte → synthèse → dépôt en rappel 🔔 ─────────────────

async def executer(registre, *, forcer: bool = False,
                   jour: datetime | None = None) -> dict:
    """Génère le briefing du jour et le dépose comme rappel proactif.

    Idempotent : si un briefing existe déjà pour cette date (lu ou non), on ne
    régénère pas — sauf `forcer=True`. Appelé chaque matin par l'horloge (S29),
    et exposé en `POST /briefing/executer` pour le tester ou le rejouer.
    """
    jour = jour or _aujourdhui()
    cle = "briefing:" + jour.strftime("%Y-%m-%d")
    proactif.init_db()
    if proactif.existe_cle(cle):
        if not forcer:
            return {"ok": True, "statut": "deja_fait", "cle": cle}
        proactif.supprimer_cle(cle)  # forcer = régénérer (remplace, ne duplique pas)

    faits = await collecter(registre, jour=jour)
    res = await rediger(faits)
    if not res.ok:
        logger.warning("Briefing : synthèse impossible (%s)", res.erreur)
        return {"ok": False, "statut": "echec_synthese",
                "erreur": res.erreur, "faits": faits}

    texte = res.contenu.strip()
    titre = "Briefing du " + jour.strftime("%A %d %B")
    # La clé est libre (aucun rappel `briefing:<date>`) : `_ajouter` insère.
    proactif._ajouter("briefing", titre, texte, cle)
    logger.info("Briefing du %s déposé (modèle %s, coût %.4f$).",
                cle, res.modele_utilise, res.cout_usd)
    return {
        "ok": True, "statut": "cree", "cle": cle, "titre": titre,
        "briefing": texte, "modele": res.modele_utilise,
        "cout_usd": res.cout_usd, "faits": faits,
    }
