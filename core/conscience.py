"""Conscience de soi (S65) — le Cœur sait décrire son propre corps.

S63 a DÉCOUVERT le schéma corporel (catalogue des capacités déclarées au manifest),
S64 l'a CÂBLÉ en outils du LLM. S65 le retourne vers l'INTÉRIEUR : l'assistant peut
enfin décrire son anatomie JUSTE au lieu de la confabuler (le défaut ressenti via
Télégram — il « inventait » ce qu'il savait faire). Deux surfaces, un seul principe :

  • un DIGEST compact injecté dans le contexte (même motif que le digest d'identité S48,
    `identite.resume_texte`) — volontairement court (coût LLM, cf. S138) : il nomme les
    organes, donne le nombre d'outils, et RENVOIE à l'outil pour le détail ;
  • un OUTIL `mes_capacites` qui rend l'anatomie DÉTAILLÉE à la demande (la liste exacte
    des organes et des outils réellement actifs) — la « look it up » qui tue la
    confabulation : on répond depuis une source de vérité, pas depuis la mémoire du modèle.

Source de vérité : les manifests (registre) + la liste d'outils réellement présentée au
LLM (`outils.outils_pour`). Rien n'est inventé : un organe absent du registre n'existe
pas, un outil absent de la liste active n'est pas appelable. Honnêteté avant poésie.

Aucune dépendance vers `outils` (qui, lui, importe ce module) : la liste d'outils et le
prédicat « est-ce une action ? » sont INJECTÉS, ce qui évite tout cycle d'import.
"""

# Métaphore du corps (épopée « Organisme vivant ») : un libellé d'organe par brique.
# CURÉ à la main pour la justesse poétique, mais NON bloquant : une brique absente de
# cette table apparaît quand même, nommée par son `role` de manifest — le système nerveux
# qui se découvre reste vrai (ajouter une brique suffit à lui donner un organe).
_ORGANES = {
    "gateway":       "cerveau (pensée — Gateway LLM)",
    "memoire":       "mémoire (souvenirs de la solution et sur toi)",
    "ecoute":        "oreilles (mot-clé vocal, « comme Siri »)",
    "connexion":     "voix vers le monde (messageries : Télégram…)",
    "calcul":        "muscle (puissance de calcul déportée — le Muscle)",
    "forge":         "mains (agents IA, RAG, CRM, factures, paiements)",
    "generateur":    "mains (fabrication d'applications)",
    "app-builder":   "mains (fabrication d'applications)",
    "studio":        "imagination (récits audio en série)",
    "personnages":   "imagination (personnages holistiques, casting vocal)",
    "video":         "imagination (vidéo : teasers, portraits animés)",
    "transcription": "ouïe (audio → texte souverain)",
    "agenda":        "agenda (rendez-vous, pont Google consenti)",
    "donnees":       "registres (données saisies dans les apps)",
    "etl":           "tri (documents déposés → dossiers, classement)",
    "audit":         "proprioception (audit de l'usine)",
    "oria":          "visage (interface de collaboration)",
}


def organe_de(manifest: dict) -> str:
    """Libellé d'organe d'une brique : table curée, sinon repli honnête sur son rôle."""
    nom = manifest.get("nom", "")
    if nom in _ORGANES:
        return _ORGANES[nom]
    return manifest.get("role") or nom or "organe"


def organes(registre) -> list[dict]:
    """Le corps que le Cœur commande : un dict par brique (sauf le noyau = moi-même).

    Chaque entrée reste fidèle au manifest (description, statut, port, offre…) ; rien
    n'est inventé. Trié par nom pour une sortie stable."""
    out: list[dict] = []
    for nom, m in sorted(registre.briques.items()):
        if nom == "noyau":  # c'est MOI (le Cœur), pas un organe que je commande
            continue
        out.append({
            "brique": nom,
            "organe": organe_de(m),
            "role": m.get("role", ""),
            "description": m.get("description", ""),
            "statut": m.get("statut", ""),
            "port": m.get("port"),
            "offre": list(m.get("offre") or []),
            "nb_capacites": len(m.get("capacites") or []),
        })
    return out


def _organes_courts(orgs: list[dict]) -> list[str]:
    """Libellés d'organe sans la parenthèse, dédupliqués (« mains » n'apparaît qu'une fois)."""
    vus: list[str] = []
    for o in orgs:
        court = o["organe"].split(" (")[0]
        if court not in vus:
            vus.append(court)
    return vus


def digest(registre, nb_outils: int) -> str:
    """Digest court (à injecter dans le contexte) : nomme les organes + règle anti-confabulation.

    Volontairement compact (une fois par conversation, coût LLM borné, S138). Vide si le
    registre n'expose aucune brique (rien à dire honnêtement)."""
    orgs = organes(registre)
    if not orgs:
        return ""
    noms = ", ".join(_organes_courts(orgs))
    return (
        f"Ton corps — Workplace — est vivant : {len(orgs)} organes ({noms}). "
        f"Tu agis sur eux par {nb_outils} outils concrets. "
        "RÈGLE D'HONNÊTETÉ : ne DEVINE jamais ton anatomie ni tes capacités. Si on te "
        "demande ce que tu sais faire, qui tu es, ou comment tu es fait, appelle d'abord "
        "l'outil `mes_capacites` et réponds à partir de son résultat — n'invente aucun "
        "organe ni aucun pouvoir absent de cette liste."
    )


def anatomie(registre, outils_specs: list[dict], est_action) -> dict:
    """Anatomie DÉTAILLÉE rendue par l'outil `mes_capacites` : organes + outils réels.

    `outils_specs` : la liste d'outils RÉELLEMENT présentée au LLM (`outils.outils_pour`),
    au format function-calling. `est_action(nom)` : prédicat « effet de bord ? ». Tout est
    lu d'une source de vérité — c'est ce qui permet de répondre juste plutôt que d'inventer."""
    orgs = organes(registre)
    outs: list[dict] = []
    for spec in outils_specs or []:
        fn = spec.get("function", {})
        nom = fn.get("name", "")
        if not nom:
            continue
        outs.append({
            "nom": nom,
            "description": fn.get("description", ""),
            "action": bool(est_action(nom)),
        })
    return {
        "corps": "Workplace",
        "je_suis": "le Cœur (noyau) : je décide et j'orchestre les organes ; je pense "
                   "via le cerveau (Gateway LLM) et mon pouls est l'horloge.",
        "organes": orgs,
        "nb_organes": len(orgs),
        "outils": outs,
        "nb_outils": len(outs),
        "note": "Anatomie RÉELLE, lue dans les manifests des briques et la liste d'outils "
                "active. Tout organe ou outil absent d'ici n'existe pas — ne l'invente pas. "
                "Un organe au statut 'a_tester' est branché mais pas encore prouvé en vrai.",
    }
