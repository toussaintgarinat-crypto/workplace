import json


def prompt_plan_app(audit: dict) -> str:
    nom = audit.get("nom_entreprise", "Entreprise inconnue")
    territoire = audit.get("territoire") or {}
    flux = audit.get("flux") or {}
    problemes = audit.get("problemes") or {}
    priorites = audit.get("priorites") or {}

    canvas = territoire.get("business_model_canvas") or {}
    ddd = territoire.get("ddd") or {}
    glossaire = territoire.get("glossaire_metier") or []
    swot = priorites.get("swot") or {}
    moscow = priorites.get("moscow") or {}
    vsm = flux.get("value_stream_map") or {}
    toc = problemes.get("theory_of_constraints") or {}
    okrs = priorites.get("okrs_proposes") or []

    contexte = json.dumps({
        "nom_entreprise": nom,
        "proposition_valeur": canvas.get("proposition_valeur"),
        "segments_clients": canvas.get("segments_clients"),
        "forces": swot.get("forces"),
        "faiblesses": swot.get("faiblesses"),
        "opportunites": swot.get("opportunites"),
        "menaces": swot.get("menaces"),
        "goulot_principal": toc.get("goulot_principal"),
        "efficacite_flux_pct": vsm.get("efficacite_flux_pct"),
        "must_have": moscow.get("must"),
        "objectifs_okr": [o.get("objectif") for o in okrs[:3]],
        # ── Vocabulaire métier (langage ubiquitaire) ──
        "bounded_contexts": ddd.get("bounded_contexts"),
        "agregats": ddd.get("agregats"),
        "glossaire_metier": glossaire,
    }, ensure_ascii=False, indent=2)

    return f"""Voici l'analyse stratégique de l'entreprise "{nom}" :
{contexte}

RÈGLE DE VOCABULAIRE — la plus importante : cette application doit parler la langue de l'entreprise.
Utilise SYSTÉMATIQUEMENT les "terme_entreprise" du glossaire_metier et les noms des "agregats"/"bounded_contexts"
ci-dessus dans TOUS les libellés que tu génères (navigation, entités, KPIs, actions, titres). N'invente pas de
termes génériques ("Items", "Produits", "Module 1") si l'entreprise a son propre mot.

Génère un JSON avec EXACTEMENT ces clés pour configurer son tableau de bord applicatif :

- "nom_app" : nom court et percutant pour l'application (ex: "AlphaOps", "VentesPilot")
- "sous_titre" : slogan ou description en une ligne (max 80 caractères)
- "secteur" : secteur d'activité détecté (ex: "Commerce B2B", "Services RH", "Industrie")
- "couleur_principale" : code hex correspondant au secteur (ex: "#1D4ED8" pour finance, "#059669" pour commerce)
- "couleur_secondaire" : couleur complémentaire en hex
- "resume_executif" : 3 phrases résumant la situation de l'entreprise, ses défis principaux et la valeur de cette app
- "navigation" : liste de 3 à 6 sections opérationnelles de l'app, NOMMÉES d'après les bounded_contexts/le vocabulaire de l'entreprise. Chaque section avec :
    - "id" : identifiant court en minuscules sans espaces (ex: "atelier", "commandes")
    - "label" : le libellé affiché, dans les mots de l'entreprise (ex: "Atelier floral", "Réservations")
    - "icone" : nom d'icône Bootstrap Icons (ex: "bi-flower1", "bi-calendar-check")
- "entites" : liste des 2 à 5 objets métier manipulés par l'app, repris des "agregats". Ce sont de VRAIS modules opérationnels (on doit pouvoir créer/lister des enregistrements). Chaque entité avec :
    - "id" : identifiant court en minuscules sans espaces ni accents (ex: "devis", "client", "chantier")
    - "nom" : le terme EXACT de l'entreprise au singulier (ex: "Composition florale", "Adhérent", "Devis")
    - "description" : à quoi sert cette entité dans l'entreprise (1 phrase)
    - "icone" : nom d'icône Bootstrap Icons
    - "champs" : liste de 3 à 6 attributs, chacun un OBJET avec :
        - "cle" : identifiant court sans espaces ni accents (ex: "client", "montant", "date_pose", "statut")
        - "label" : le libellé affiché, dans le vocabulaire de l'entreprise (ex: "Nom du client", "Montant TTC")
        - "type" : un parmi "texte" | "nombre" | "montant" | "date" | "statut"
        - "options" : UNIQUEMENT si type = "statut", liste de 2 à 5 valeurs possibles (ex: ["Brouillon","Envoyé","Accepté","Refusé"])
    - "exemples" : 2 à 3 enregistrements d'exemple réalistes et cohérents avec l'entreprise, chacun un objet {{cle: valeur}} reprenant les "cle" des champs ci-dessus
- "glossaire" : reprends le glossaire_metier ci-dessus (liste de {{"terme_generique","terme_entreprise","definition"}}), corrigé/complété si besoin. Sert à expliquer le vocabulaire de l'app.
- "kpis" : liste de 4 à 6 indicateurs clés détectés dans l'audit, libellés avec le vocabulaire de l'entreprise, chacun avec :
    - "nom" : libellé court
    - "valeur" : valeur estimée ou constatée (string)
    - "unite" : unité (%, jours, €, etc.)
    - "icone" : nom d'icône Bootstrap Icons (ex: "bi-graph-up-arrow", "bi-clock", "bi-people")
    - "tendance" : "hausse" | "baisse" | "stable" | "alerte"
- "actions_immediates" : liste de 3 actions prioritaires à lancer, chacune avec :
    - "titre" : titre court de l'action
    - "description" : explication en 1 phrase
    - "priorite" : "critique" | "haute" | "normale"
    - "icone" : nom d'icône Bootstrap Icons
- "message_introduction" : phrase d'accueil personnalisée affichée en haut du dashboard (max 120 caractères)
"""
