import json

from langues import consigne_langue


_SECTIONS_CDC = [
    ("objectifs", "Objectifs"),
    ("utilisateurs", "Utilisateurs"),
    ("fonctionnalites", "Fonctionnalités"),
    ("regles_metier", "Règles métier"),
    ("architecture", "Architecture"),
    ("api", "API"),
    ("base_de_donnees", "Base de données"),
    ("interfaces", "Interfaces"),
    ("integrations", "Intégrations"),
    ("securite", "Sécurité"),
    ("tests", "Tests"),
    ("criteres_acceptation", "Critères d'acceptation"),
]


def prompt_cahier_des_charges(audit: dict, langue: str = "fr") -> str:
    nom = audit.get("nom_entreprise", "Entreprise inconnue")
    territoire = audit.get("territoire") or {}
    flux = audit.get("flux") or {}
    problemes = audit.get("problemes") or {}
    priorites = audit.get("priorites") or {}

    contexte = json.dumps({
        "nom_entreprise": nom,
        "business_model_canvas": territoire.get("business_model_canvas"),
        "ddd": territoire.get("ddd"),
        "glossaire_metier": territoire.get("glossaire_metier"),
        "value_stream_map": flux.get("value_stream_map"),
        "processus_cles": flux.get("processus_cles"),
        "ishikawa": problemes.get("ishikawa"),
        "theory_of_constraints": problemes.get("theory_of_constraints"),
        "moscow": priorites.get("moscow"),
        "chemin_critique": priorites.get("chemin_critique"),
        "swot": priorites.get("swot"),
        "okrs_proposes": priorites.get("okrs_proposes"),
    }, ensure_ascii=False, indent=2)

    cles = "\n".join(f'- "{cle}" : section "{titre}"' for cle, titre in _SECTIONS_CDC)

    return f"""Voici l'audit complet de l'entreprise "{nom}" :
{contexte}

Rédige un cahier des charges formel pour l'application sur-mesure à livrer à cette
entreprise. Utilise le vocabulaire de l'entreprise (glossaire_metier, ddd) partout où
c'est pertinent. Base les fonctionnalités sur le moscow (Must/Should/Could/Won't).

Retourne un JSON avec exactement ces clés, chacune un TEXTE markdown (pas un objet) :
{cles}

Chaque section doit être un texte markdown autonome et lisible (pas de titre ## à
l'intérieur, il est ajouté automatiquement), 2 à 6 paragraphes ou listes selon la section.
Ne mentionne PAS de chiffrage ROI — cette section est ajoutée séparément.{consigne_langue(langue)}"""


def prompt_plan_app(audit: dict, langue: str = "fr") -> str:
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
{consigne_langue(langue)}"""


def prompt_revue(audit: dict, plan: dict, usage: dict,
                 nouveaux_docs: list[str] | None = None, langue: str = "fr") -> str:
    """Prompt du re-audit post-livraison (S31) : usage réel + audit initial +
    nouveaux documents → proposition d'incrément, à valider avant toute génération."""
    nom = audit.get("nom_entreprise", "Entreprise")
    problemes = audit.get("problemes") or {}
    priorites = audit.get("priorites") or {}
    pareto_initial = (problemes.get("pareto") or {})
    moscow = priorites.get("moscow") or {}

    modules = [
        {"id": e.get("id"), "nom": e.get("nom"), "description": e.get("description")}
        for e in (plan or {}).get("entites") or [] if isinstance(e, dict)
    ]

    contexte = json.dumps({
        "nom_entreprise": nom,
        "modules_livres": modules,
        "usage_reel": {
            "pareto": usage.get("pareto"),
            "modules_dormants": usage.get("modules_dormants"),
            "total_enregistrements": usage.get("total_enregistrements"),
            "non_mesures_souverainete": usage.get("non_consenties"),
        },
        "pareto_audit_initial": pareto_initial,
        "must_have_initiaux": moscow.get("must"),
    }, ensure_ascii=False, indent=2)

    docs = "\n\n---\n\n".join((nouveaux_docs or []))[:6000]
    bloc_docs = f"\n\nNOUVEAUX DOCUMENTS depuis la livraison :\n{docs}" if docs else ""

    return f"""L'application livrée à "{nom}" tourne depuis un moment. Voici son USAGE RÉEL
mesuré (uniquement sur les modules que le client a consenti à partager), comparé à
l'audit initial :
{contexte}{bloc_docs}

Tu es l'analyste qui propose au cabinet le PROCHAIN INCRÉMENT de cette app. Compare
l'usage réel à l'intention initiale (le Pareto a-t-il changé ? quels modules sont
massivement utilisés, lesquels dorment ?) et tiens compte des nouveaux documents.

Produis UNIQUEMENT un JSON avec EXACTEMENT ces clés :
- "resume" : 2-3 phrases — ce que l'usage révèle et la direction proposée.
- "pareto_commentaire" : 1 phrase comparant le Pareto réel au Pareto initial.
- "modules_proposes" : liste de 0 à 3 NOUVEAUX modules à ajouter, chacun {{"nom", "raison"}}
  (raison ancrée dans l'usage observé ou les nouveaux documents).
- "modules_sous_utilises" : liste des modules existants peu/pas utilisés, chacun
  {{"nom", "raison"}} — à confirmer, fusionner ou retirer.

N'invente pas d'usage non mesuré. Si un module est "dormant", dis-le franchement.{consigne_langue(langue)}"""


def prompt_schema_module(nom_entreprise: str, module_nom: str, raison: str,
                         audit: dict | None = None, langue: str = "fr") -> str:
    """Prompt du schéma fin d'un module proposé (S34) : à partir du nom du module retenu
    pour l'incrément, dérive ses **champs typés** dans le vocabulaire de l'entreprise —
    au lieu d'un schéma CRUD générique."""
    audit = audit or {}
    glossaire = ((audit.get("territoire") or {}).get("glossaire_metier")) or []
    contexte = json.dumps({
        "nom_entreprise": nom_entreprise,
        "module_a_concevoir": module_nom,
        "raison_de_l_ajout": raison,
        "glossaire_metier": glossaire,
    }, ensure_ascii=False, indent=2)

    return f"""On ajoute à l'application de "{nom_entreprise}" un nouveau module métier :
« {module_nom} ». Contexte :
{contexte}

Conçois le SCHÉMA de ce module (les attributs d'un enregistrement), dans le vocabulaire
exact de l'entreprise (réutilise le glossaire_metier si pertinent ; pas de termes
génériques si l'entreprise a son propre mot).

Produis UNIQUEMENT un JSON avec EXACTEMENT ces clés :
- "icone" : nom d'icône Bootstrap Icons adapté au module (ex: "bi-calendar-check", "bi-cash-coin")
- "champs" : liste de 3 à 6 attributs, chacun un OBJET avec :
    - "cle" : identifiant court sans espaces ni accents (ex: "client", "montant", "date_pose", "statut")
    - "label" : libellé affiché, dans le vocabulaire de l'entreprise
    - "type" : un parmi "texte" | "nombre" | "montant" | "date" | "statut"
    - "options" : UNIQUEMENT si type = "statut", 2 à 5 valeurs possibles

N'ajoute aucune autre clé.{consigne_langue(langue)}"""
