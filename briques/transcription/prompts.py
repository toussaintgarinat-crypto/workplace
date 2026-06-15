"""PROMPTS de synthèse (résumé + points d'action) — fonctions PURES, testables sans réseau.

La synthèse est faite par l'« économe gratuit » (≈0 $) via la Gateway, exactement comme le
briefing S30. Ici on ne fait que CONSTRUIRE le prompt : on sépare « quoi demander » (ici)
de « appeler le LLM » (resume.py). Le résumé sort dans la langue demandée (motif S37→S45).
"""

# Consigne de langue de sortie (la transcription peut être dans une autre langue).
LANGUES = {
    "fr": "en français",
    "en": "in English",
    "es": "en español",
    "ar": "بالعربية",
    "pt": "em português",
    "de": "auf Deutsch",
    "it": "in italiano",
}


def consigne_langue(langue: str | None) -> str:
    return LANGUES.get((langue or "fr").lower()[:2], LANGUES["fr"])


def prompt_resume(langue: str | None = None) -> str:
    """Prompt système : transformer une transcription en notes de réunion exploitables."""
    return (
        "Tu es un assistant de prise de notes de réunion. À partir de la TRANSCRIPTION "
        f"fournie, produis des notes claires {consigne_langue(langue)}. "
        "Réponds STRICTEMENT en JSON valide, sans texte autour, avec ces clés :\n"
        '  "resume"        : un paragraphe de synthèse (~80 mots) ;\n'
        '  "points_action" : liste de tâches concrètes (verbe + responsable si connu), '
        "ou liste vide ;\n"
        '  "themes"        : liste de 3 à 6 mots-clés des sujets abordés ;\n'
        '  "decisions"     : liste des décisions prises, ou liste vide.\n'
        "N'INVENTE RIEN : si une information n'est pas dans la transcription, ne la mets pas. "
        "Si la transcription est trop courte ou vide, rends des listes vides et un résumé bref."
    )


def repli_heuristique(texte: str) -> dict:
    """Repli HONNÊTE sans LLM : extrait les premières phrases comme résumé grossier.

    Utilisé quand la Gateway est absente/injoignable. On le DIT (`source: heuristique`)
    et on n'invente ni points d'action ni décisions — on ne fait que tronquer."""
    propre = " ".join((texte or "").split())
    phrases = []
    buf = ""
    for ch in propre:
        buf += ch
        if ch in ".!?…" and len(buf) > 12:
            phrases.append(buf.strip())
            buf = ""
        if len(phrases) >= 3:
            break
    if buf.strip() and len(phrases) < 3:
        phrases.append(buf.strip())
    resume = " ".join(phrases).strip() or propre[:240]
    return {"resume": resume, "points_action": [], "themes": [], "decisions": [],
            "source": "heuristique"}
