"""Résumé de boîte mail — le « digest » que l'assistant lit à voix haute.

On délègue la rédaction du résumé à la Gateway LLM (modèle gratuit par défaut, cost-first),
comme `restaurant/souvenir.py`. Repli **HONNÊTE** : si la Gateway est injoignable ou répond
mal, on retombe sur un digest FACTUEL construit localement (les plus importants d'abord, par
catégorie) — jamais d'analyse inventée. Le champ `genere_par` dit toujours la vérité
(« ia » ou « local »).

Entrée = des messages DÉJÀ enrichis (categorie + score) par `domaine.py`. Ce module ne touche
ni la base ni IMAP : on lui passe l'état déjà calculé.
"""
from __future__ import annotations

import os

import httpx

import domaine

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://host.docker.internal:4001")
GATEWAY_KEY = os.getenv("GATEWAY_KEY", "")
GATEWAY_MODEL = os.getenv("GATEWAY_MODEL", "free/google/gemma-4-31b-it")

_ETIQUETTES = {
    domaine.FACTURE: "💶 Factures / paiements",
    domaine.RENDEZ_VOUS: "📅 Rendez-vous",
    domaine.PERSONNEL: "👤 Personnel",
    domaine.NOTIFICATION: "🔔 Notifications",
    domaine.NEWSLETTER: "📰 Newsletters / promos",
    domaine.AUTRE: "✉️ Autres",
}

PROMPT_DIGEST = (
    "Tu es l'assistant personnel de l'utilisateur et tu lui fais le point sur sa boîte mail. "
    "On te donne la liste des messages (expéditeur, sujet, catégorie, importance, lu/non-lu). "
    "Règles STRICTES : reste FIDÈLE à la liste, n'invente AUCUN message ni détail absent. "
    "Commence par ce qui demande une ACTION ou est URGENT, puis le reste, regroupé. "
    "Sois bref (4 à 8 phrases), concret et bienveillant, en {langue}. Tutoie l'utilisateur. "
    "Termine par une suggestion d'action si pertinent (ex. « tu veux que je prépare une réponse à Thomas ? »)."
)

_LANGUES = {"fr": "français", "en": "anglais", "es": "espagnol"}


def digest_factuel(messages: list[dict], lang: str = "fr") -> str:
    """Digest LOCAL (sans LLM) : compte les non-lus, liste les plus importants par catégorie."""
    if not messages:
        return "Ta boîte est vide (ou rien à synchroniser)."
    non_lus = sum(1 for m in messages if not m.get("lu"))
    tries = domaine.trier(messages)
    lignes = [f"{len(messages)} message(s), dont {non_lus} non lu(s). À regarder en priorité :"]
    for m in tries[:5]:
        marque = "•" if m.get("lu") else "🔵"
        lignes.append(f"  {marque} [{m.get('score', 0)}] {m.get('de_nom') or m.get('de')} — "
                      f"{m.get('sujet') or '(sans sujet)'}")
    groupes = domaine.grouper_par_categorie(tries)
    repartition = ", ".join(f"{_ETIQUETTES.get(c, c)}: {len(v)}" for c, v in groupes.items())
    lignes.append("Répartition — " + repartition + ".")
    return "\n".join(lignes)


def _lignes_pour_llm(messages: list[dict]) -> str:
    tries = domaine.trier(messages)
    out = []
    for m in tries[:30]:
        etat = "non lu" if not m.get("lu") else "lu"
        out.append(f"- [{etat}, importance {m.get('score', 0)}, {m.get('categorie')}] "
                   f"{m.get('de_nom') or m.get('de')} : {m.get('sujet') or '(sans sujet)'}")
    return "\n".join(out)


async def _completer(systeme: str, tache: str) -> str:
    if not GATEWAY_MODEL:
        raise RuntimeError("Aucun modèle LLM configuré (GATEWAY_MODEL).")
    headers = {"Authorization": f"Bearer {GATEWAY_KEY}"} if GATEWAY_KEY else {}
    payload = {"model": GATEWAY_MODEL, "temperature": 0.4,
               "messages": [{"role": "system", "content": systeme},
                            {"role": "user", "content": tache}]}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{GATEWAY_URL}/v1/chat/completions", json=payload, headers=headers)
        r.raise_for_status()
        return (r.json()["choices"][0]["message"]["content"] or "").strip()


PROMPT_BROUILLON = (
    "Tu rédiges, à la place de l'utilisateur, un BROUILLON de réponse à un email reçu. "
    "On te donne l'email d'origine et, éventuellement, une consigne. Règles : reste fidèle au "
    "contexte, n'invente aucun fait ni engagement chiffré non demandé ; ton poli et naturel, en "
    "{langue} ; signe « [Ton nom] » (l'utilisateur ajustera). Rends UNIQUEMENT le corps du message, "
    "sans objet ni en-têtes."
)


def _brouillon_factuel(message: dict, lang: str = "fr") -> str:
    """Brouillon LOCAL minimal et honnête (sans LLM) : un accusé de réception poli, à compléter."""
    nom = message.get("de_nom") or message.get("de") or ""
    if lang == "en":
        return (f"Hello {nom},\n\nThank you for your message. I have taken note and will get back "
                f"to you shortly.\n\n[Your name]")
    return (f"Bonjour {nom},\n\nMerci pour votre message. J'en prends bonne note et reviens vers "
            f"vous rapidement.\n\n[Ton nom]")


async def rediger_brouillon(message: dict, instruction: str = "", lang: str = "fr") -> dict:
    """Prépare un brouillon de réponse (LLM si dispo, sinon gabarit poli honnête). NE l'envoie pas.
    Renvoie {corps, genere_par:"ia"|"local", note}."""
    factuel = _brouillon_factuel(message, lang)
    langue = _LANGUES.get(lang, "français")
    tache = (f"Email reçu de {message.get('de_nom') or message.get('de')} — "
             f"objet : {message.get('sujet')}\n\n{message.get('corps') or message.get('extrait')}\n\n"
             + (f"Consigne : {instruction}\n\n" if instruction else "")
             + "Rédige le brouillon de réponse (corps uniquement).")
    try:
        corps = await _completer(PROMPT_BROUILLON.format(langue=langue), tache)
    except Exception:  # noqa: BLE001
        return {"corps": factuel, "genere_par": "local",
                "note": "Rédaction assistée indisponible : brouillon minimal à compléter."}
    if not corps:
        return {"corps": factuel, "genere_par": "local", "note": "Réponse vide : brouillon minimal."}
    return {"corps": corps[:3000], "genere_par": "ia", "note": ""}


PROMPT_COMPOSER = (
    "Tu rédiges, à la place de l'utilisateur, un email NEUF à partir de ce qu'il a dicté. "
    "Ta mission : (1) CORRIGER l'orthographe, la grammaire et la ponctuation de la dictée ; "
    "(2) la METTRE EN FORME en email classique et professionnel en {langue} : une formule "
    "d'appel (« Bonjour, » ou « Bonjour [Nom], »), un corps clair en paragraphes, une formule "
    "de politesse de clôture (« Cordialement, »), puis la signature « [Ton nom] » sur la dernière "
    "ligne. Règles STRICTES : reste FIDÈLE à la dictée, n'invente AUCUN fait, chiffre, date ni "
    "engagement absent ; n'ajoute pas d'objet ni d'en-têtes dans le corps. "
    "Réponds UNIQUEMENT par un objet JSON : {{\"sujet\": \"...\", \"corps\": \"...\"}} — un objet "
    "court et fidèle au contenu, et le corps mis en forme. Aucun texte hors du JSON."
)


def _composer_factuel(destinataire: str, dictee: str, sujet: str = "",
                      lang: str = "fr") -> dict:
    """Mise en forme LOCALE minimale et honnête (sans LLM) : on encadre la dictée d'une formule
    d'appel et d'une signature, SANS rien corriger ni inventer. L'utilisateur ajustera."""
    texte = (dictee or "").strip()
    if lang == "en":
        corps = f"Hello,\n\n{texte}\n\nBest regards,\n[Your name]"
        suj = sujet or (texte.splitlines()[0][:60] if texte else "(no subject)")
    else:
        corps = f"Bonjour,\n\n{texte}\n\nCordialement,\n[Ton nom]"
        suj = sujet or (texte.splitlines()[0][:60] if texte else "(sans objet)")
    return {"sujet": suj, "corps": corps, "genere_par": "local",
            "note": "Rédaction assistée indisponible : mise en forme minimale, à relire (la dictée "
                    "n'a PAS été corrigée)."}


async def rediger_nouveau(destinataire: str, dictee: str, sujet: str = "",
                          lang: str = "fr") -> dict:
    """Compose un email NEUF à partir d'une dictée : corrige et met en forme (LLM si dispo, sinon
    gabarit honnête NON corrigé). NE l'envoie pas. Renvoie {sujet, corps, genere_par, note}."""
    factuel = _composer_factuel(destinataire, dictee, sujet, lang)
    if not (dictee or "").strip():
        return {**factuel, "note": "Dictée vide : rien à rédiger."}
    langue = _LANGUES.get(lang, "français")
    tache = (f"Destinataire : {destinataire or '(non précisé)'}\n"
             + (f"Objet souhaité : {sujet}\n" if sujet else "Objet : à proposer.\n")
             + f"\nDictée de l'utilisateur (à corriger et mettre en forme) :\n{dictee}\n\n"
             + "Rends le JSON {sujet, corps}.")
    try:
        brut = await _completer(PROMPT_COMPOSER.format(langue=langue), tache)
        import json
        debut, fin = brut.find("{"), brut.rfind("}")
        donnees = json.loads(brut[debut:fin + 1]) if debut != -1 and fin != -1 else {}
        corps = (donnees.get("corps") or "").strip()
        suj = (donnees.get("sujet") or sujet or "").strip()
    except Exception:  # noqa: BLE001 — repli honnête, jamais d'erreur opaque
        return factuel
    if not corps:
        return factuel
    return {"sujet": suj[:200] or factuel["sujet"], "corps": corps[:3000],
            "genere_par": "ia", "note": ""}


async def resumer(messages: list[dict], lang: str = "fr") -> dict:
    """Construit le digest de la boîte. Tente la Gateway, retombe sur le digest FACTUEL local
    en cas d'échec. Renvoie {texte, genere_par:"ia"|"local", note}."""
    factuel = digest_factuel(messages, lang)
    if not messages:
        return {"texte": factuel, "genere_par": "local", "note": "Boîte vide."}
    langue = _LANGUES.get(lang, "français")
    tache = ("Voici les messages de la boîte (triés par importance) :\n"
             + _lignes_pour_llm(messages) + "\n\nFais le point, uniquement le texte.")
    try:
        texte = await _completer(PROMPT_DIGEST.format(langue=langue), tache)
    except Exception:  # noqa: BLE001 — repli honnête, jamais d'erreur opaque côté client
        return {"texte": factuel, "genere_par": "local",
                "note": "Digest assisté indisponible (assistant hors ligne) : voici le récap factuel."}
    if not texte:
        return {"texte": factuel, "genere_par": "local", "note": "Réponse vide : récap factuel."}
    return {"texte": texte[:2000], "genere_par": "ia", "note": ""}
