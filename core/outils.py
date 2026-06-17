"""Outils de l'assistant du Cœur (Sprints S7/S8).

L'assistant n'est pas cantonné à l'usine : il sert **toute la solution**. Chaque
outil est une spec function-calling + un répartiteur `executer(nom, args)` qui
appelle les **contrats HTTP existants** des briques (ETL, Audit, Générateur,
Données, Mémoire) et les fonctions internes du Cœur (orchestrateur, cycle de vie).
Aucune logique métier n'est réécrite.

Familles :
  • LECTURE : consulter l'état (entreprises, documents, apps, données, mémoire,
    santé des briques).
  • ACTION  : livrer/décrocher/reprendre une entreprise, ingérer un document,
    créer un enregistrement, mémoriser un souvenir. Toute action est **gardée par
    confirmation** : refus tant que `confirme=true` n'est pas passé, et message de
    confirmation renvoyé au modèle pour qu'il demande l'accord de l'utilisateur.
"""

import asyncio
import json
import os
import uuid

import httpx

import agenda
import cycle_de_vie
import orchestrateur


# ── Catalogue (specs function-calling) ───────────────────────────────────────

def _p(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


OUTILS: list[dict] = [
    # — LECTURE —
    {"type": "function", "function": {
        "name": "lister_entreprises",
        "description": "Liste les entreprises livrées et leur statut (livree, decrochee, en_cours, erreur). À appeler en premier pour retrouver l'identifiant (livraison_id) avant toute action.",
        "parameters": _p({}, [])}},
    {"type": "function", "function": {
        "name": "details_entreprise",
        "description": "Détail d'une entreprise : étapes, app, audit, dossier, erreurs.",
        "parameters": _p({"livraison_id": {"type": "string"}}, ["livraison_id"])}},
    {"type": "function", "function": {
        "name": "etat_briques",
        "description": "Liste les briques de la solution (ETL, Audit, Générateur, Données, Mémoire…) et leur santé.",
        "parameters": _p({}, [])}},
    {"type": "function", "function": {
        "name": "chercher_documents",
        "description": "Cherche dans les documents ingérés (ETL) et leur classement. Sans filtre, liste tout. Filtre possible par texte (q), catégorie, projet ou entreprise.",
        "parameters": _p({
            "q": {"type": "string", "description": "Filtre texte sur le nom/contenu (optionnel)."},
            "categorie": {"type": "string", "description": "Filtre par catégorie (devis, facture, contrat…)."},
            "projet": {"type": "string", "description": "Filtre par dossier de projet (ex. « prochain sprint »)."},
            "entreprise_id": {"type": "string", "description": "Filtre par entreprise rattachée (livraison_id)."},
        }, [])}},
    {"type": "function", "function": {
        "name": "lister_dossiers",
        "description": "Liste les dossiers de documents : projets et catégories, avec le nombre de documents dans chacun.",
        "parameters": _p({}, [])}},
    {"type": "function", "function": {
        "name": "lire_document",
        "description": "Lit le texte extrait d'un document de l'ETL.",
        "parameters": _p({"doc_id": {"type": "string"}}, ["doc_id"])}},
    {"type": "function", "function": {
        "name": "lister_apps",
        "description": "Liste les applications générées (Générateur).",
        "parameters": _p({}, [])}},
    {"type": "function", "function": {
        "name": "consulter_donnees",
        "description": "Résume les enregistrements saisis dans une app (Données) : nombre par entité.",
        "parameters": _p({"app_id": {"type": "string"}}, ["app_id"])}},
    {"type": "function", "function": {
        "name": "memoire_rappeler",
        "description": "Cherche dans la mémoire. 'espace' = 'solution' (usine, entreprises, projets) ou 'perso' (préférences/faits sur l'utilisateur lui-même). Défaut : solution.",
        "parameters": _p({
            "requete": {"type": "string"},
            "espace": {"type": "string", "enum": ["solution", "perso"]},
        }, ["requete"])}},
    {"type": "function", "function": {
        "name": "agenda_consulter",
        "description": "Liste les rendez-vous/événements de l'agenda personnel sur une période. 'debut' et 'fin' au format ISO 8601 (ex. 2026-06-06T00:00:00). Sans période, renvoie les prochains événements.",
        "parameters": _p({
            "debut": {"type": "string", "description": "Début de la plage (ISO 8601)."},
            "fin": {"type": "string", "description": "Fin de la plage (ISO 8601)."},
        }, [])}},
    {"type": "function", "function": {
        "name": "agenda_lister",
        "description": "Liste les agendas (calendriers) accessibles : l'agenda perso et les agendas partagés, avec le rôle de l'utilisateur (owner/editor/viewer) et l'id de chacun. Utile avant d'inviter quelqu'un ou de voir les membres.",
        "parameters": _p({}, [])}},
    {"type": "function", "function": {
        "name": "forge_capacites",
        "description": "État et capacités de la brique Forge (agents IA, RAG, vectorisation) : ce que Forge sait faire et si son moteur est en ligne. À appeler pour répondre « que peut faire Forge ? » ou « est-ce que Forge tourne ? ». Lecture seule.",
        "parameters": _p({}, [])}},
    {"type": "function", "function": {
        "name": "forge_rag_chercher",
        "description": "Cherche dans les documents ingérés dans le RAG de Forge (recherche sémantique) et renvoie les passages pertinents. À utiliser pour « que dit le doc sur X ? » ou « cherche X dans Forge ». Lecture seule (aucune confirmation).",
        "parameters": _p({
            "q": {"type": "string", "description": "La question ou les termes à rechercher."},
        }, ["q"])}},
    {"type": "function", "function": {
        "name": "forge_factures_lister",
        "description": "Liste les devis et factures de Forge avec le chiffre d'affaires (encaissé, en attente). À utiliser pour « mes factures impayées », « mon CA », « liste mes devis ». Pour les impayés, utilise statut='envoyée'. Lecture seule (aucune confirmation).",
        "parameters": _p({
            "type": {"type": "string", "enum": ["facture", "devis"], "description": "Filtre par type (optionnel)."},
            "statut": {"type": "string", "enum": ["brouillon", "envoyée", "payée", "annulée"], "description": "Filtre par statut (optionnel). 'envoyée' = impayé en attente."},
        }, [])}},
    {"type": "function", "function": {
        "name": "forge_crm_lister",
        "description": "Liste les prospects/clients du CRM de Forge avec le pipeline commercial (valeur estimée totale, ventilation par statut). À utiliser pour « mes prospects », « mon pipeline », « qui est en cours de négo ». Filtre 'statut' optionnel. Lecture seule (aucune confirmation).",
        "parameters": _p({
            "statut": {"type": "string", "description": "Filtre par statut (optionnel), ex. 'prospect', 'qualifié', 'gagné', 'perdu'."},
        }, [])}},
    {"type": "function", "function": {
        "name": "forge_paiement_etat",
        "description": "État du paiement en ligne Stripe : encaissement RÉEL (clé test/live configurée) ou SIMULÉ (mode mock), abonnement courant et historique des paiements. À utiliser pour « est-ce que les paiements marchent ? », « Stripe est-il configuré ? », « mes paiements ». Ne révèle jamais la clé. Lecture seule (aucune confirmation).",
        "parameters": _p({}, [])}},
    {"type": "function", "function": {
        "name": "forge_relances_apercu",
        "description": "Aperçu (dry-run) des relances de factures impayées qui SERAIENT envoyées (J+7/J+15/J+30), avec le montant total à recouvrer et les factures ignorées (sans email/échéance). N'envoie RIEN. À utiliser pour « qui dois-je relancer ? », « mes impayés à relancer ». Lecture seule (aucune confirmation).",
        "parameters": _p({}, [])}},

    # — ACTION (gardées par confirmation) —
    {"type": "function", "function": {
        "name": "livrer_entreprise",
        "description": "Lance une livraison (audit→génération) sur les documents déjà dans l'ETL. ACTION : confirme=true requis après accord.",
        "parameters": _p({
            "nom_entreprise": {"type": "string"},
            "persistance": {"type": "string", "enum": ["hebergee", "autonome"]},
            "messagerie": {"type": "boolean"},
            "packager": {"type": "boolean"},
            "confirme": {"type": "boolean"},
        }, ["nom_entreprise"])}},
    {"type": "function", "function": {
        "name": "decrocher_entreprise",
        "description": "Décroche une entreprise (dossier portable + retrait des bases centrales). ACTION DESTRUCTRICE : confirme=true requis après accord.",
        "parameters": _p({"livraison_id": {"type": "string"}, "confirme": {"type": "boolean"}}, ["livraison_id"])}},
    {"type": "function", "function": {
        "name": "reprendre_entreprise",
        "description": "Réinjecte une entreprise décrochée pour la modifier. ACTION : confirme=true requis après accord.",
        "parameters": _p({"livraison_id": {"type": "string"}, "confirme": {"type": "boolean"}}, ["livraison_id"])}},
    {"type": "function", "function": {
        "name": "ingerer_document",
        "description": "Ingère un document dans l'ETL depuis une URL. ACTION : confirme=true requis après accord.",
        "parameters": _p({"url": {"type": "string"}, "confirme": {"type": "boolean"}}, ["url"])}},
    {"type": "function", "function": {
        "name": "classer_document",
        "description": "Range/ajuste le classement d'un document déjà ingéré : catégorie, mots-clés (tags), entreprise rattachée (entreprise_id), dossier de projet, résumé. Ne passe que les champs à changer. ACTION : confirme=true requis après accord.",
        "parameters": _p({
            "doc_id": {"type": "string"},
            "categorie": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "entreprise_id": {"type": "string", "description": "livraison_id de l'entreprise à rattacher."},
            "projet": {"type": "string", "description": "Nom du dossier de projet (ex. « prochain sprint »)."},
            "resume": {"type": "string"},
            "confirme": {"type": "boolean"},
        }, ["doc_id"])}},
    {"type": "function", "function": {
        "name": "creer_enregistrement",
        "description": "Crée un enregistrement dans une app (Données). ACTION : confirme=true requis après accord.",
        "parameters": _p({
            "app_id": {"type": "string"},
            "entite": {"type": "string", "description": "Identifiant de l'entité (ex. devis, chantier)."},
            "donnees": {"type": "object", "description": "Champs de l'enregistrement."},
            "confirme": {"type": "boolean"},
        }, ["app_id", "entite", "donnees"])}},
    {"type": "function", "function": {
        "name": "memoire_retenir",
        "description": "Mémorise un souvenir/fait/préférence. 'espace' = 'solution' (usine, entreprises) ou 'perso' (ce qui concerne l'utilisateur : ses préférences, habitudes, faits perso). Défaut : solution. ACTION : confirme=true requis après accord.",
        "parameters": _p({
            "contenu": {"type": "string"},
            "titre": {"type": "string"},
            "espace": {"type": "string", "enum": ["solution", "perso"]},
            "confirme": {"type": "boolean"},
        }, ["contenu"])}},
    {"type": "function", "function": {
        "name": "agenda_creer_evenement",
        "description": "Ajoute un rendez-vous/événement à l'agenda (effet immédiat, pas de confirmation). 'debut' et 'fin' au format ISO 8601 (utilise la date/heure courante fournie pour interpréter « demain », « lundi prochain »…). Si l'heure de fin n'est pas précisée, mets +1h.",
        "parameters": _p({
            "titre": {"type": "string"},
            "debut": {"type": "string", "description": "Date/heure de début (ISO 8601)."},
            "fin": {"type": "string", "description": "Date/heure de fin (ISO 8601). Si non précisée, mets +1h."},
            "lieu": {"type": "string"},
            "description": {"type": "string"},
        }, ["titre", "debut", "fin"])}},
    {"type": "function", "function": {
        "name": "agenda_deplacer_evenement",
        "description": "Replanifie un événement existant (nouvelles dates, effet immédiat). Retrouve d'abord son event_id via agenda_consulter.",
        "parameters": _p({
            "event_id": {"type": "string"},
            "debut": {"type": "string", "description": "Nouveau début (ISO 8601)."},
            "fin": {"type": "string", "description": "Nouvelle fin (ISO 8601)."},
        }, ["event_id", "debut", "fin"])}},
    {"type": "function", "function": {
        "name": "agenda_supprimer_evenement",
        "description": "Annule (supprime) un événement de l'agenda. Retrouve d'abord son event_id via agenda_consulter. ACTION DESTRUCTRICE : confirme=true requis après accord.",
        "parameters": _p({
            "event_id": {"type": "string"},
            "confirme": {"type": "boolean"},
        }, ["event_id"])}},
    {"type": "function", "function": {
        "name": "agenda_creer_partage",
        "description": "Crée un nouvel agenda (calendrier) partageable, distinct de l'agenda perso (effet immédiat, pas de confirmation). Le créateur en est propriétaire et peut ensuite inviter des personnes via agenda_inviter. Renvoie l'id de l'agenda créé.",
        "parameters": _p({
            "nom": {"type": "string", "description": "Nom de l'agenda (ex. « Famille », « Équipe chantier »)."},
            "description": {"type": "string"},
            "couleur": {"type": "string", "description": "Couleur hex, ex. #3B82F6."},
        }, ["nom"])}},
    {"type": "function", "function": {
        "name": "agenda_inviter",
        "description": "Génère un lien d'invitation à un agenda partagé pour donner l'accès à quelqu'un. Récupère d'abord le calendar_id via agenda_lister. Renvoie un lien et un token à transmettre à l'invité. ACTION (donne un accès) : confirme=true requis après accord.",
        "parameters": _p({
            "calendar_id": {"type": "string", "description": "Id de l'agenda à partager (via agenda_lister)."},
            "role": {"type": "string", "enum": ["viewer", "editor"], "description": "viewer = lecture seule ; editor = peut modifier. Défaut viewer."},
            "expire_heures": {"type": "integer", "description": "Durée de validité du lien en heures (défaut 72)."},
            "email": {"type": "string", "description": "Email de l'invité (optionnel, informatif)."},
            "confirme": {"type": "boolean"},
        }, ["calendar_id"])}},
    {"type": "function", "function": {
        "name": "forge_rag_ingerer",
        "description": "Ingère un document dans la base RAG de Forge (vectorisation) pour pouvoir l'interroger ensuite. ACTION (écrit dans Forge) : confirme=true requis après accord.",
        "parameters": _p({
            "nom": {"type": "string", "description": "Nom/titre du document."},
            "contenu": {"type": "string", "description": "Le texte du document à ingérer."},
            "confirme": {"type": "boolean"},
        }, ["nom", "contenu"])}},
    {"type": "function", "function": {
        "name": "forge_lancer_agent",
        "description": "Lance un agent IA de Forge sur une tâche (il raisonne et peut utiliser des outils, via la Gateway). ACTION (exécution dans Forge) : confirme=true requis après accord.",
        "parameters": _p({
            "objectif": {"type": "string", "description": "Ce que l'agent doit accomplir."},
            "contexte": {"type": "string", "description": "Contexte utile (optionnel)."},
            "confirme": {"type": "boolean"},
        }, ["objectif"])}},
    {"type": "function", "function": {
        "name": "forge_facture_creer",
        "description": "Crée un devis ou une facture dans Forge (numérotation et calcul HT/TVA/TTC automatiques). ACTION (écrit dans Forge) : confirme=true requis après accord.",
        "parameters": _p({
            "client": {"type": "string", "description": "Nom du client."},
            "lignes": {"type": "array", "description": "Lignes du document.", "items": {"type": "object", "properties": {
                "description": {"type": "string"},
                "quantite": {"type": "number"},
                "prix_unitaire": {"type": "number"},
                "tva": {"type": "number", "description": "Taux TVA en % (défaut 20)."},
            }, "required": ["description", "prix_unitaire"]}},
            "type": {"type": "string", "enum": ["facture", "devis"], "description": "Défaut : facture."},
            "email": {"type": "string", "description": "Email du client (optionnel)."},
            "tva_taux": {"type": "number", "description": "Taux TVA par défaut (%)."},
            "notes": {"type": "string"},
            "echeance": {"type": "string", "description": "Date d'échéance (ISO, optionnel)."},
            "confirme": {"type": "boolean"},
        }, ["client", "lignes"])}},
    {"type": "function", "function": {
        "name": "forge_facture_statut",
        "description": "Change le statut d'une facture/devis : la passer 'payée' (encaissement → entre dans le CA), 'envoyée', 'annulée'. Récupère d'abord son id via forge_factures_lister. ACTION : confirme=true requis après accord.",
        "parameters": _p({
            "id": {"type": "string", "description": "Id du document (via forge_factures_lister)."},
            "statut": {"type": "string", "enum": ["brouillon", "envoyée", "payée", "annulée"]},
            "confirme": {"type": "boolean"},
        }, ["id", "statut"])}},
    {"type": "function", "function": {
        "name": "forge_facture_transformer",
        "description": "Transforme un devis accepté en facture (crée la facture, marque le devis transformé). Récupère d'abord l'id du devis via forge_factures_lister. ACTION : confirme=true requis après accord.",
        "parameters": _p({
            "id": {"type": "string", "description": "Id du devis à transformer."},
            "confirme": {"type": "boolean"},
        }, ["id"])}},
    {"type": "function", "function": {
        "name": "forge_crm_creer",
        "description": "Ajoute un prospect/client dans le CRM de Forge. ACTION (écrit dans Forge) : confirme=true requis après accord.",
        "parameters": _p({
            "nom": {"type": "string", "description": "Nom du contact."},
            "entreprise": {"type": "string"},
            "email": {"type": "string"},
            "telephone": {"type": "string"},
            "statut": {"type": "string", "description": "Étape du pipeline (défaut 'prospect')."},
            "valeur": {"type": "integer", "description": "Valeur estimée de l'affaire en euros."},
            "notes": {"type": "string"},
            "confirme": {"type": "boolean"},
        }, ["nom"])}},
    {"type": "function", "function": {
        "name": "forge_crm_modifier",
        "description": "Met à jour un prospect / le fait avancer dans le pipeline (changer le statut, ajuster la valeur, corriger les coordonnées). Récupère d'abord son id via forge_crm_lister. Ne passe que les champs à changer. ACTION : confirme=true requis après accord.",
        "parameters": _p({
            "id": {"type": "string", "description": "Id du prospect (via forge_crm_lister)."},
            "statut": {"type": "string", "description": "Nouvelle étape (ex. 'qualifié', 'gagné', 'perdu')."},
            "valeur": {"type": "integer", "description": "Valeur estimée (€)."},
            "nom": {"type": "string"},
            "entreprise": {"type": "string"},
            "email": {"type": "string"},
            "telephone": {"type": "string"},
            "notes": {"type": "string"},
            "confirme": {"type": "boolean"},
        }, ["id"])}},
    {"type": "function", "function": {
        "name": "forge_paiement_lien",
        "description": "Crée un lien de paiement Stripe pour un plan d'abonnement (starter/pro/enterprise), à envoyer au client pour qu'il paie en ligne. Si Stripe est configuré le lien est réel, sinon il est simulé (clairement marqué). ACTION (crée une session de paiement) : confirme=true requis après accord.",
        "parameters": _p({
            "plan": {"type": "string", "enum": ["starter", "pro", "enterprise"], "description": "Plan d'abonnement à facturer."},
            "confirme": {"type": "boolean"},
        }, ["plan"])}},
    {"type": "function", "function": {
        "name": "forge_relances_envoyer",
        "description": "Lance l'envoi des relances dues pour les factures impayées (emails J+7/J+15/J+30, une seule fois par niveau et par facture). Vérifie d'abord avec forge_relances_apercu. ACTION (envoie des emails réels) : confirme=true requis après accord.",
        "parameters": _p({"confirme": {"type": "boolean"}}, [])}},
    {"type": "function", "function": {
        "name": "forge_facture_envoyer",
        "description": "Envoie une facture au client par email et la passe au statut 'envoyée' (démarre le compteur des relances). Récupère d'abord son id via forge_factures_lister. La facture doit avoir un email client. ACTION (envoie un email réel) : confirme=true requis après accord.",
        "parameters": _p({
            "id": {"type": "string", "description": "Id de la facture (via forge_factures_lister)."},
            "confirme": {"type": "boolean"},
        }, ["id"])}},

    # — STUDIO (brique audio-séries 6060 ; lecture + production gardée) —
    {"type": "function", "function": {
        "name": "studio_series_lister",
        "description": "Liste les séries audio du Studio (titre, langue, nb de chapitres/personnages/tomes). À utiliser pour « mes séries », « qu'est-ce qu'il y a dans le studio ». Lecture seule (aucune confirmation).",
        "parameters": _p({}, [])}},
    {"type": "function", "function": {
        "name": "studio_serie_lire",
        "description": "Détail d'une série du Studio : bible (univers, personnages, intrigue…), épisodes produits, réglages. Récupère d'abord l'id via studio_series_lister. Lecture seule (aucune confirmation).",
        "parameters": _p({
            "serie_id": {"type": "string", "description": "Id de la série (via studio_series_lister)."},
        }, ["serie_id"])}},
    {"type": "function", "function": {
        "name": "studio_personnages_lister",
        "description": "Liste la distribution (personnages + voix figées) d'une série du Studio. Récupère l'id via studio_series_lister. Lecture seule (aucune confirmation).",
        "parameters": _p({
            "serie_id": {"type": "string", "description": "Id de la série (via studio_series_lister)."},
        }, ["serie_id"])}},
    {"type": "function", "function": {
        "name": "studio_serie_creer",
        "description": "Crée une nouvelle série audio dans le Studio. ACTION : confirme=true requis après accord.",
        "parameters": _p({
            "titre": {"type": "string", "description": "Titre de la série."},
            "idee": {"type": "string", "description": "Idée / genre de départ (optionnel)."},
            "langue": {"type": "string", "description": "Langue de travail (ex. fr, en, es). Défaut fr."},
            "public_cible": {"type": "string", "description": "Public visé (optionnel)."},
            "confirme": {"type": "boolean"},
        }, ["titre"])}},
    {"type": "function", "function": {
        "name": "studio_episode_produire",
        "description": "Produit l'épisode SUIVANT d'une série (Scénariste + Script Doctor), à partir de la bible existante. Récupère l'id via studio_series_lister. ACTION : confirme=true requis après accord.",
        "parameters": _p({
            "serie_id": {"type": "string", "description": "Id de la série (via studio_series_lister)."},
            "confirme": {"type": "boolean"},
        }, ["serie_id"])}},
    {"type": "function", "function": {
        "name": "studio_express",
        "description": "Mode express : le Showrunner complète lui-même les pièces manquantes de la bible puis produit un épisode — de l'idée à l'épisode en un coup. Idéal pour « fais-moi un épisode de telle série ». ACTION : confirme=true requis après accord.",
        "parameters": _p({
            "serie_id": {"type": "string", "description": "Id de la série (via studio_series_lister)."},
            "idee": {"type": "string", "description": "Idée/orientation pour l'épisode (optionnel)."},
            "confirme": {"type": "boolean"},
        }, ["serie_id"])}},
    {"type": "function", "function": {
        "name": "studio_voix_lister",
        "description": "Liste les voix disponibles pour une langue (catalogue du serveur de voix). À utiliser avant de distribuer une voix à un personnage. Lecture seule (aucune confirmation).",
        "parameters": _p({
            "langue": {"type": "string", "description": "Code langue (fr, en, es…). Défaut fr."},
        }, [])}},
    {"type": "function", "function": {
        "name": "studio_bible_proposer",
        "description": "Co-création de la bible : un agent créatif PROPOSE des options pour une dimension (genre, univers, personnages, intrigue, choix) — ne fige RIEN. Utilise studio_bible_decider pour retenir une option. Génératif mais non destructif (aucune confirmation).",
        "parameters": _p({
            "serie_id": {"type": "string", "description": "Id de la série (via studio_series_lister)."},
            "dimension": {"type": "string", "enum": ["genre", "univers", "personnages", "intrigue", "choix"],
                          "description": "Dimension de la bible à explorer."},
            "mon_idee": {"type": "string", "description": "Piste/contrainte de l'utilisateur à intégrer (optionnel)."},
        }, ["serie_id", "dimension"])}},
    {"type": "function", "function": {
        "name": "studio_distribution_proposer",
        "description": "Le Directeur de Casting PROPOSE une distribution (personnages + voix) cohérente avec la bible — ne stocke RIEN. Pour créer réellement un rôle, utilise studio_perso_creer. Génératif non destructif (aucune confirmation).",
        "parameters": _p({
            "serie_id": {"type": "string", "description": "Id de la série (via studio_series_lister)."},
            "combien": {"type": "integer", "description": "Nombre de rôles à proposer (2 à 8, défaut 4)."},
            "mon_idee": {"type": "string", "description": "Piste de l'utilisateur à intégrer (optionnel)."},
        }, ["serie_id"])}},
    {"type": "function", "function": {
        "name": "studio_bible_decider",
        "description": "Fige (retient) le contenu d'une dimension de la bible. Utilise d'abord studio_bible_proposer pour explorer. ACTION : confirme=true requis après accord.",
        "parameters": _p({
            "serie_id": {"type": "string", "description": "Id de la série (via studio_series_lister)."},
            "dimension": {"type": "string", "enum": ["genre", "univers", "personnages", "intrigue", "choix"]},
            "choix": {"type": "string", "description": "Le contenu retenu pour cette dimension."},
            "confirme": {"type": "boolean"},
        }, ["serie_id", "dimension", "choix"])}},
    {"type": "function", "function": {
        "name": "studio_perso_creer",
        "description": "Ajoute un personnage à la distribution d'une série. ACTION : confirme=true requis après accord.",
        "parameters": _p({
            "serie_id": {"type": "string", "description": "Id de la série (via studio_series_lister)."},
            "nom": {"type": "string", "description": "Nom du personnage."},
            "role": {"type": "string", "description": "Rôle (protagoniste, antagoniste, secondaire…) (optionnel)."},
            "description": {"type": "string", "description": "Description du personnage (optionnel)."},
            "confirme": {"type": "boolean"},
        }, ["serie_id", "nom"])}},
    {"type": "function", "function": {
        "name": "studio_audio_produire",
        "description": "Produit l'audio d'un épisode déjà écrit (voix figées par personnage). Sans numéro, prend le dernier épisode. ACTION : confirme=true requis après accord.",
        "parameters": _p({
            "serie_id": {"type": "string", "description": "Id de la série (via studio_series_lister)."},
            "n": {"type": "integer", "description": "Numéro d'épisode à sonoriser (optionnel : défaut = le dernier)."},
            "confirme": {"type": "boolean"},
        }, ["serie_id"])}},

    # — TRANSCRIPTION (brique audio→texte souveraine 5980 ; notes d'appel/réunion) —
    {"type": "function", "function": {
        "name": "transcription_etat",
        "description": "État de la brique de transcription : moteur actif, s'il est souverain (Whisper local), si la synthèse de notes (économe gratuit) est dispo, destinations d'archivage. Lecture seule.",
        "parameters": _p({}, [])}},
    {"type": "function", "function": {
        "name": "transcription_depuis_url",
        "description": "Transcrit un audio accessible par URL puis en produit des NOTES (résumé, points d'action, décisions, thèmes). Pour « transcris/résume cet enregistrement », « fais le compte-rendu de cet audio ». L'upload d'un fichier ou la capture d'un appel se font dans le front de la brique, pas ici. Lecture seule (ne range rien).",
        "parameters": _p({
            "url": {"type": "string", "description": "URL directe d'un fichier audio (mp3/m4a/wav/webm…)."},
            "langue": {"type": "string", "description": "Langue de sortie des notes (fr, en, es…). Défaut : langue de l'audio."},
            "diarisation": {"type": "boolean", "description": "Identifier les intervenants si le moteur le permet (optionnel)."},
        }, ["url"])}},
    {"type": "function", "function": {
        "name": "transcription_resumer",
        "description": "Transforme un TEXTE déjà transcrit (notes brutes, transcription collée) en notes structurées : résumé, points d'action, décisions, thèmes. Lecture seule.",
        "parameters": _p({
            "texte": {"type": "string", "description": "Le texte à synthétiser."},
            "langue": {"type": "string", "description": "Langue de sortie (fr, en, es…) (optionnel)."},
        }, ["texte"])}},
    {"type": "function", "function": {
        "name": "transcription_destinations",
        "description": "Liste les destinations d'archivage des notes (mémoire souveraine, dossier/drive) et laquelle est par défaut. Lecture seule.",
        "parameters": _p({}, [])}},
    {"type": "function", "function": {
        "name": "transcription_archiver",
        "description": "Range des notes (issues de transcription_depuis_url/transcription_resumer) dans la destination CHOISIE : « memoire » (souverain, défaut) ou « dossier » (fichier .md, ex. dossier synchronisé par un drive). ACTION : confirme=true requis après accord.",
        "parameters": _p({
            "resume": {"type": "string", "description": "Le résumé / corps des notes."},
            "titre": {"type": "string", "description": "Titre des notes (optionnel)."},
            "points_action": {"type": "array", "items": {"type": "string"}, "description": "Points d'action (optionnel)."},
            "decisions": {"type": "array", "items": {"type": "string"}, "description": "Décisions prises (optionnel)."},
            "themes": {"type": "array", "items": {"type": "string"}, "description": "Thèmes/mots-clés (optionnel)."},
            "destination": {"type": "string", "enum": ["memoire", "dossier", "gdrive"], "description": "Où ranger : memoire (souverain, défaut), dossier (.md local/drive synchronisé), gdrive (API Google Drive)."},
            "dossier": {"type": "string", "description": "Chemin du dossier (destination=dossier) ou ID du dossier Drive (destination=gdrive). Sinon valeur par défaut de la brique."},
            "langue": {"type": "string", "description": "Langue des notes (optionnel)."},
            "confirme": {"type": "boolean"},
        }, ["resume"])}},

    # — PERSONNAGES (atelier holistique cosmique, brique 5900) —
    {"type": "function", "function": {
        "name": "personnage_creer_holistique",
        "description": "Crée un personnage HOLISTIQUE (atelier cosmique, brique personnages) à partir d'infos de naissance DICTÉES : prénoms, date, et si possible heure et ville. Renvoie son portrait (archétype, forces, à travailler, pierre d'équilibrage) déduit de plusieurs traditions. Pour « crée-moi un personnage né le… à… », « génère une fiche cosmique pour… ». La simple génération ne stocke RIEN (aucune confirmation). Pour ENREGISTRER la fiche (enregistrer=true) ou l'AJOUTER à une série du Studio (serie_id), c'est une ACTION : confirme=true requis après accord. Récupère un serie_id via studio_series_lister.",
        "parameters": _p({
            "prenoms": {"type": "string", "description": "Prénom(s) du personnage."},
            "nom": {"type": "string", "description": "Nom de famille (optionnel)."},
            "date_naissance": {"type": "string", "description": "Date de naissance au format AAAA-MM-JJ."},
            "heure_naissance": {"type": "string", "description": "Heure de naissance HH:MM (optionnel : affine ascendant / Lune)."},
            "ville": {"type": "string", "description": "Ville de naissance (optionnel : géocodée pour l'astro). Ex. « Toulouse »."},
            "utc_offset": {"type": "number", "description": "Décalage local→UTC à la naissance, en heures (optionnel ; ex. 2 pour l'heure d'été en France)."},
            "enregistrer": {"type": "boolean", "description": "Enregistrer la fiche cosmique (récupérable plus tard). ACTION : confirme=true requis."},
            "serie_id": {"type": "string", "description": "Ajouter le personnage à cette série du Studio (id via studio_series_lister). ACTION : confirme=true requis."},
            "nom_scene": {"type": "string", "description": "Nom de scène à donner dans la série (optionnel : défaut = prénoms). Le nom cosmique d'origine est conservé."},
            "confirme": {"type": "boolean"},
        }, ["prenoms", "date_naissance"])}},
]

OUTILS_ACTION = {
    "livrer_entreprise", "decrocher_entreprise", "reprendre_entreprise",
    "ingerer_document", "classer_document", "creer_enregistrement", "memoire_retenir",
    "agenda_supprimer_evenement", "agenda_inviter",
    "forge_rag_ingerer", "forge_lancer_agent",
    "forge_facture_creer", "forge_facture_statut", "forge_facture_transformer",
    "forge_crm_creer", "forge_crm_modifier", "forge_paiement_lien",
    "forge_relances_envoyer", "forge_facture_envoyer",
    "studio_serie_creer", "studio_episode_produire", "studio_express",
    "studio_bible_decider", "studio_perso_creer", "studio_audio_produire",
    "transcription_archiver",
}


def _confirmation(action: str, cible: str) -> str:
    return json.dumps({
        "confirmation_requise": True, "action": action, "cible": cible,
        "message": f"Action « {action} » sur « {cible} » PAS encore exécutée. "
                   "Si l'utilisateur a DÉJÀ donné son accord dans la conversation "
                   "(ex. « oui », « vas-y », « confirme »), tu DOIS rappeler MAINTENANT le "
                   "même outil avec confirme=true — n'émets AUCUN texte, ne redemande PAS "
                   "l'accord une seconde fois. Si l'accord n'a pas encore été donné, "
                   "demande-lui simplement de confirmer.",
    }, ensure_ascii=False)


def _resume_liv(l: dict) -> dict:
    return {"livraison_id": l.get("id"), "nom_entreprise": l.get("nom_entreprise"),
            "statut": l.get("statut"), "app_id": l.get("app_id"), "dossier": l.get("dossier")}


def _base(registre, nom: str) -> str:
    return orchestrateur._brique_base(registre, nom)


def _espace_memoire(espace: str | None) -> str | None:
    """Mappe l'espace logique de l'assistant → nom d'espace de la brique Mémoire.
    'solution' (défaut) → None (= espace « Workplace » côté brique) ; 'perso' → « Perso »."""
    return "Perso" if (espace or "").lower() == "perso" else None


# ── Répartiteur ──────────────────────────────────────────────────────────────

async def executer(nom: str, args: dict, registre) -> str:
    """Exécute un outil et renvoie une chaîne (résultat ou message) pour le LLM."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # — LECTURE —
            if nom == "lister_entreprises":
                liv = [_resume_liv(l) for l in orchestrateur.lister_livraisons()]
                return json.dumps({"entreprises": liv, "total": len(liv)}, ensure_ascii=False)

            if nom == "details_entreprise":
                l = orchestrateur.lire_livraison(args.get("livraison_id", ""))
                return json.dumps(l, ensure_ascii=False) if l else "Aucune entreprise avec cet identifiant."

            if nom == "etat_briques":
                return json.dumps(await _etat_briques(client, registre), ensure_ascii=False)

            if nom == "chercher_documents":
                params = {k: args[k] for k in ("categorie", "projet", "entreprise_id")
                          if args.get(k)}
                params["limite"] = 200
                r = await client.get(f"{_base(registre, 'etl')}/documents", params=params)
                docs = r.json().get("documents", []) if r.status_code < 400 else []
                q = (args.get("q") or "").lower()
                if q:
                    docs = [d for d in docs if q in json.dumps(d, ensure_ascii=False).lower()]
                apercu = [{"id": d.get("id"), "nom": d.get("nom"), "type": d.get("type_mime"),
                           "classement": d.get("classement")} for d in docs]
                return json.dumps({"documents": apercu, "total": len(apercu)}, ensure_ascii=False)

            if nom == "lister_dossiers":
                r = await client.get(f"{_base(registre, 'etl')}/dossiers")
                return json.dumps(r.json(), ensure_ascii=False) if r.status_code < 400 else "ETL injoignable."

            if nom == "lire_document":
                r = await client.get(f"{_base(registre, 'etl')}/documents/{args.get('doc_id','')}")
                if r.status_code >= 400:
                    return "Document introuvable."
                d = r.json()
                return json.dumps({"id": d.get("id"), "nom": d.get("nom"),
                                   "texte": (d.get("texte_extrait") or "")[:2000]}, ensure_ascii=False)

            if nom == "lister_apps":
                r = await client.get(f"{_base(registre, 'generateur')}/apps")
                return json.dumps(r.json(), ensure_ascii=False) if r.status_code < 400 else "Générateur injoignable."

            if nom == "consulter_donnees":
                r = await client.get(f"{_base(registre, 'donnees')}/apps/{args.get('app_id','')}/resume")
                return json.dumps(r.json(), ensure_ascii=False) if r.status_code < 400 else "Données injoignables."

            if nom == "memoire_rappeler":
                params = {"q": args.get("requete", "")}
                esp = _espace_memoire(args.get("espace"))
                if esp:
                    params["espace"] = esp
                r = await client.get(f"{_base(registre, 'memoire')}/rappeler", params=params)
                return json.dumps(r.json(), ensure_ascii=False) if r.status_code < 400 else "Mémoire injoignable."

            if nom == "agenda_consulter":
                evts = await agenda.lister_evenements(registre, args.get("debut"), args.get("fin"))
                apercu = [{"event_id": e.get("id"), "titre": e.get("title"),
                           "debut": e.get("start_at"), "fin": e.get("end_at"),
                           "lieu": e.get("location")} for e in evts]
                return json.dumps({"evenements": apercu, "total": len(apercu)}, ensure_ascii=False)

            if nom == "agenda_lister":
                cals = await agenda.lister_agendas(registre)
                apercu = [{"calendar_id": c.get("id"), "nom": c.get("name"),
                           "role": c.get("role"), "defaut": c.get("is_default")}
                          for c in cals]
                return json.dumps({"agendas": apercu, "total": len(apercu)}, ensure_ascii=False)

            if nom == "forge_capacites":
                return await _forge_capacites(client, registre)

            if nom == "forge_rag_chercher":
                q = (args.get("q") or "").strip()
                if not q:
                    return "Précise ce que tu veux chercher dans Forge."
                return await _forge_appel(client, registre, "GET", "/rag/chercher",
                                          params={"q": q}, timeout=30)

            if nom == "forge_factures_lister":
                params = {k: args[k] for k in ("type", "statut") if args.get(k)}
                return await _forge_appel(client, registre, "GET", "/facturation",
                                          params=params, timeout=30)

            if nom == "forge_crm_lister":
                params = {"statut": args["statut"]} if args.get("statut") else {}
                return await _forge_appel(client, registre, "GET", "/crm",
                                          params=params, timeout=30)

            if nom == "forge_paiement_etat":
                return await _forge_appel(client, registre, "GET", "/paiement/etat", timeout=15)

            if nom == "forge_relances_apercu":
                return await _forge_appel(client, registre, "GET", "/relances/apercu", timeout=30)

            # — ACTION —
            if nom == "livrer_entreprise":
                cible = args.get("nom_entreprise") or "entreprise"
                if not args.get("confirme"):
                    return _confirmation("livrer", cible)
                return await _livrer(registre, args)

            if nom == "decrocher_entreprise":
                lid = args.get("livraison_id", "")
                cible = (orchestrateur.lire_livraison(lid) or {}).get("nom_entreprise") or lid
                if not args.get("confirme"):
                    return _confirmation("décrocher", cible)
                return json.dumps(await cycle_de_vie.decrocher(registre, lid), ensure_ascii=False)

            if nom == "reprendre_entreprise":
                lid = args.get("livraison_id", "")
                cible = (orchestrateur.lire_livraison(lid) or {}).get("nom_entreprise") or lid
                if not args.get("confirme"):
                    return _confirmation("reprendre", cible)
                return json.dumps(await cycle_de_vie.reprendre(registre, lid), ensure_ascii=False)

            if nom == "ingerer_document":
                url = args.get("url", "")
                if not args.get("confirme"):
                    return _confirmation("ingérer le document", url)
                r = await client.post(f"{_base(registre, 'etl')}/ingerer/url", json={"url": url})
                return json.dumps(r.json(), ensure_ascii=False) if r.status_code < 400 else f"Échec ingestion : {r.text}"

            if nom == "classer_document":
                doc_id = args.get("doc_id", "")
                if not args.get("confirme"):
                    return _confirmation("classer le document", doc_id)
                classement = {k: args[k] for k in
                              ("categorie", "tags", "entreprise_id", "projet", "resume")
                              if args.get(k) is not None}
                r = await client.patch(
                    f"{_base(registre, 'etl')}/documents/{doc_id}/classement", json=classement)
                return json.dumps(r.json(), ensure_ascii=False) if r.status_code < 400 else f"Échec classement : {r.text}"

            if nom == "creer_enregistrement":
                app_id, entite = args.get("app_id", ""), args.get("entite", "")
                if not args.get("confirme"):
                    return _confirmation("créer un enregistrement", f"{entite} (app {app_id})")
                r = await client.post(
                    f"{_base(registre, 'donnees')}/apps/{app_id}/entites/{entite}/enregistrements",
                    json=args.get("donnees") or {})
                return json.dumps(r.json(), ensure_ascii=False) if r.status_code < 400 else f"Échec : {r.text}"

            if nom == "memoire_retenir":
                if not args.get("confirme"):
                    return _confirmation("mémoriser", (args.get("titre") or args.get("contenu", ""))[:60])
                corps_mem = {"contenu": args.get("contenu", ""), "titre": args.get("titre")}
                esp = _espace_memoire(args.get("espace"))
                if esp:
                    corps_mem["espace"] = esp
                r = await client.post(f"{_base(registre, 'memoire')}/retenir", json=corps_mem)
                return json.dumps(r.json(), ensure_ascii=False) if r.status_code < 400 else f"Échec mémorisation : {r.text}"

            if nom == "agenda_creer_evenement":
                titre = args.get("titre") or "Événement"
                evt = await agenda.creer_evenement(
                    registre, titre, args.get("debut", ""), args.get("fin", ""),
                    args.get("lieu"), args.get("description"))
                return json.dumps({"cree": True, "event_id": evt.get("id"), "titre": evt.get("title"),
                                   "debut": evt.get("start_at"), "fin": evt.get("end_at")}, ensure_ascii=False)

            if nom == "agenda_deplacer_evenement":
                evt = await agenda.deplacer_evenement(
                    registre, args.get("event_id", ""), args.get("debut", ""), args.get("fin", ""))
                return json.dumps({"deplace": True, "event_id": evt.get("id"),
                                   "debut": evt.get("start_at"), "fin": evt.get("end_at")}, ensure_ascii=False)

            if nom == "agenda_supprimer_evenement":
                if not args.get("confirme"):
                    return _confirmation("annuler l'événement", args.get("event_id", ""))
                ok = await agenda.supprimer_evenement(registre, args.get("event_id", ""))
                return json.dumps({"supprime": ok}, ensure_ascii=False)

            if nom == "agenda_creer_partage":
                cal = await agenda.creer_agenda_partage(
                    registre, args.get("nom") or "Agenda partagé",
                    args.get("description"), args.get("couleur"))
                return json.dumps({"cree": True, "calendar_id": cal.get("id"),
                                   "nom": cal.get("name"), "role": cal.get("role")}, ensure_ascii=False)

            if nom == "agenda_inviter":
                cal_id = args.get("calendar_id", "")
                if not args.get("confirme"):
                    return _confirmation("inviter à l'agenda partagé", cal_id)
                inv = await agenda.inviter(
                    registre, cal_id, args.get("role") or "viewer",
                    args.get("expire_heures", 72), args.get("email"))
                return json.dumps({"invite": True, "calendar_id": inv.get("calendar_id"),
                                   "lien": inv.get("lien"), "token": inv.get("token"),
                                   "role": inv.get("role"), "expire_le": inv.get("expires_at")},
                                  ensure_ascii=False)

            if nom == "forge_rag_ingerer":
                nom_doc = (args.get("nom") or "document").strip()
                if not args.get("confirme"):
                    return _confirmation("ingérer dans le RAG de Forge", nom_doc)
                return await _forge_appel(client, registre, "POST", "/rag/ingerer",
                                          charge={"nom": nom_doc, "contenu": args.get("contenu", "")},
                                          timeout=60)

            if nom == "forge_lancer_agent":
                objectif = (args.get("objectif") or "").strip()
                if not args.get("confirme"):
                    return _confirmation("lancer un agent Forge", objectif[:60] or "tâche")
                charge = {"objectif": objectif}
                if args.get("contexte"):
                    charge["contexte"] = args["contexte"]
                return await _forge_appel(client, registre, "POST", "/agent/lancer",
                                          charge=charge, timeout=185)

            if nom == "forge_facture_creer":
                client_nom = (args.get("client") or "").strip()
                type_ = args.get("type") or "facture"
                if not args.get("confirme"):
                    libelle = "devis" if type_ == "devis" else "facture"
                    return _confirmation(f"créer un {libelle} Forge", client_nom or "client")
                charge = {k: args[k] for k in
                          ("client", "lignes", "type", "email", "tva_taux", "notes", "echeance")
                          if args.get(k) is not None}
                return await _forge_appel(client, registre, "POST", "/facturation",
                                          charge=charge, timeout=30)

            if nom == "forge_facture_statut":
                fid, statut = args.get("id", ""), args.get("statut", "")
                if not args.get("confirme"):
                    return _confirmation(f"passer le document au statut « {statut} »", fid)
                return await _forge_appel(client, registre, "POST", f"/facturation/{fid}/statut",
                                          charge={"statut": statut}, timeout=30)

            if nom == "forge_facture_transformer":
                fid = args.get("id", "")
                if not args.get("confirme"):
                    return _confirmation("transformer le devis en facture", fid)
                return await _forge_appel(client, registre, "POST",
                                          f"/facturation/{fid}/transformer", timeout=30)

            if nom == "forge_crm_creer":
                cible = (args.get("nom") or "prospect").strip()
                if not args.get("confirme"):
                    return _confirmation("ajouter un prospect au CRM Forge", cible)
                charge = {k: args[k] for k in
                          ("nom", "entreprise", "email", "telephone", "statut", "valeur", "notes")
                          if args.get(k) is not None}
                return await _forge_appel(client, registre, "POST", "/crm",
                                          charge=charge, timeout=30)

            if nom == "forge_crm_modifier":
                lid = args.get("id", "")
                if not args.get("confirme"):
                    cible = f"prospect {lid}" + (f" → {args['statut']}" if args.get("statut") else "")
                    return _confirmation("mettre à jour le prospect", cible)
                champs = {k: args[k] for k in
                          ("statut", "valeur", "nom", "entreprise", "email", "telephone", "notes")
                          if args.get(k) is not None}
                return await _forge_appel(client, registre, "POST", f"/crm/{lid}",
                                          charge=champs, timeout=30)

            if nom == "forge_paiement_lien":
                plan = (args.get("plan") or "").strip()
                if not args.get("confirme"):
                    return _confirmation("créer un lien de paiement Stripe", f"plan {plan}")
                return await _forge_appel(client, registre, "POST", "/paiement/lien",
                                          charge={"plan": plan}, timeout=30)

            if nom == "forge_relances_envoyer":
                if not args.get("confirme"):
                    return _confirmation("envoyer les relances d'impayés dues", "factures J+7/15/30")
                return await _forge_appel(client, registre, "POST", "/relances/executer", timeout=60)

            if nom == "forge_facture_envoyer":
                fid = args.get("id", "")
                if not args.get("confirme"):
                    return _confirmation("envoyer la facture au client par email", fid)
                return await _forge_appel(client, registre, "POST", f"/facturation/{fid}/envoyer",
                                          timeout=30)

            # — STUDIO (audio-séries) —
            if nom == "studio_series_lister":
                return await _studio_appel(client, registre, "GET", "/series", timeout=15)

            if nom == "studio_serie_lire":
                sid = args.get("serie_id", "")
                return await _studio_appel(client, registre, "GET", f"/series/{sid}", timeout=15)

            if nom == "studio_personnages_lister":
                sid = args.get("serie_id", "")
                return await _studio_appel(client, registre, "GET", f"/series/{sid}/personnages",
                                           timeout=15)

            if nom == "studio_serie_creer":
                if not args.get("confirme"):
                    return _confirmation("créer une série dans le Studio", args.get("titre", ""))
                charge = {"titre": args.get("titre", "")}
                if args.get("idee"):
                    charge["idee"] = args["idee"]
                if args.get("langue"):
                    charge["langue"] = args["langue"]
                if args.get("public_cible"):
                    charge["cible"] = args["public_cible"]   # nom de champ côté brique
                return await _studio_appel(client, registre, "POST", "/series", charge=charge,
                                           timeout=30)

            if nom == "studio_episode_produire":
                sid = args.get("serie_id", "")
                if not args.get("confirme"):
                    return _confirmation("produire l'épisode suivant de la série", sid)
                return await _studio_appel(client, registre, "POST", f"/series/{sid}/episode",
                                           charge={}, timeout=120)

            if nom == "studio_express":
                sid = args.get("serie_id", "")
                if not args.get("confirme"):
                    return _confirmation("produire un épisode express (bible auto) de la série", sid)
                charge = {"idee": args["idee"]} if args.get("idee") else {}
                return await _studio_appel(client, registre, "POST", f"/series/{sid}/express",
                                           charge=charge, timeout=120)

            if nom == "studio_voix_lister":
                return await _studio_appel(client, registre, "GET", "/voix",
                                           params={"langue": args.get("langue", "fr")}, timeout=15)

            if nom == "studio_bible_proposer":
                sid = args.get("serie_id", "")
                charge = {"dimension": args.get("dimension", "")}
                if args.get("mon_idee"):
                    charge["mon_idee"] = args["mon_idee"]
                return await _studio_appel(client, registre, "POST", f"/series/{sid}/proposer",
                                           charge=charge, timeout=60)

            if nom == "studio_distribution_proposer":
                sid = args.get("serie_id", "")
                charge = {}
                if args.get("combien"):
                    charge["combien"] = args["combien"]
                if args.get("mon_idee"):
                    charge["mon_idee"] = args["mon_idee"]
                return await _studio_appel(client, registre, "POST",
                                           f"/series/{sid}/personnages/proposer",
                                           charge=charge, timeout=60)

            if nom == "studio_bible_decider":
                sid = args.get("serie_id", "")
                if not args.get("confirme"):
                    return _confirmation("figer une dimension de la bible", args.get("dimension", ""))
                charge = {"dimension": args.get("dimension", ""), "choix": args.get("choix", "")}
                return await _studio_appel(client, registre, "POST", f"/series/{sid}/decider",
                                           charge=charge, timeout=30)

            if nom == "studio_perso_creer":
                sid = args.get("serie_id", "")
                if not args.get("confirme"):
                    return _confirmation("ajouter un personnage à la distribution", args.get("nom", ""))
                charge = {"nom": args.get("nom", "")}
                if args.get("role"):
                    charge["role"] = args["role"]
                if args.get("description"):
                    charge["description"] = args["description"]
                return await _studio_appel(client, registre, "POST", f"/series/{sid}/personnages",
                                           charge=charge, timeout=30)

            if nom == "studio_audio_produire":
                sid = args.get("serie_id", "")
                if not args.get("confirme"):
                    return _confirmation("produire l'audio de l'épisode", sid)
                charge = {"n": args["n"]} if args.get("n") else {}
                return await _studio_appel(client, registre, "POST", f"/series/{sid}/audio",
                                           charge=charge, timeout=180)

            # — PERSONNAGES (atelier holistique cosmique) —
            if nom == "personnage_creer_holistique":
                return await _personnage_holistique(client, registre, args)

            # — TRANSCRIPTION (notes d'appel/réunion) —
            if nom == "transcription_etat":
                return await _transcription_appel(client, registre, "GET", "/sante", timeout=15)

            if nom == "transcription_destinations":
                return await _transcription_appel(client, registre, "GET", "/destinations",
                                                  timeout=15)

            if nom == "transcription_depuis_url":
                charge = {"url": args.get("url", ""), "langue": args.get("langue"),
                          "diarisation": bool(args.get("diarisation"))}
                trans = await _transcription_appel(client, registre, "POST", "/transcrire-url",
                                                   charge=charge, timeout=300, brut=True)
                if not isinstance(trans, dict) or trans.get("place_holder"):
                    return json.dumps({"transcription": trans}, ensure_ascii=False)
                notes = await _transcription_appel(
                    client, registre, "POST", "/resumer",
                    charge={"texte": trans.get("texte", ""), "langue": args.get("langue")},
                    timeout=120, brut=True)
                return json.dumps({"transcription": trans, "notes": notes}, ensure_ascii=False)

            if nom == "transcription_resumer":
                charge = {"texte": args.get("texte", ""), "langue": args.get("langue")}
                return await _transcription_appel(client, registre, "POST", "/resumer",
                                                  charge=charge, timeout=120)

            if nom == "transcription_archiver":
                dest = args.get("destination") or "memoire"
                titre = args.get("titre") or "Notes"
                if not args.get("confirme"):
                    return _confirmation(f"ranger les notes ({dest})", titre)
                charge = {
                    "notes": {"resume": args.get("resume", ""),
                              "points_action": args.get("points_action") or [],
                              "decisions": args.get("decisions") or [],
                              "themes": args.get("themes") or [], "source": "assistant"},
                    "titre": args.get("titre"), "langue": args.get("langue"),
                    "destination": dest, "dossier": args.get("dossier"),
                }
                return await _transcription_appel(client, registre, "POST", "/archiver",
                                                  charge=charge, timeout=45)

            return f"Outil inconnu : {nom}"

    except ValueError as e:
        return f"Impossible : {e}"
    except cycle_de_vie.EchecCycle as e:
        return f"Échec ({nom}) : {e}"
    except RuntimeError as e:  # brique absente du registre
        return f"Indisponible ({nom}) : {e}"
    except httpx.HTTPError as e:
        return f"Brique injoignable ({nom}) : {e}"
    except Exception as e:  # noqa: BLE001
        return f"Erreur ({nom}) : {e}"


async def _livrer(registre, args: dict) -> str:
    mode = "hebergee" if args.get("persistance", "hebergee") == "hebergee" else "autonome"
    nom = args.get("nom_entreprise") or "Entreprise"
    livraison_id = str(uuid.uuid4())
    orchestrateur.creer_livraison(livraison_id, nom, mode,
                                  bool(args.get("messagerie", False)), bool(args.get("packager", False)))
    asyncio.create_task(orchestrateur.executer_pipeline(
        registre, livraison_id, [], mode, bool(args.get("messagerie", False)), bool(args.get("packager", False))))
    return json.dumps({"lancee": True, "livraison_id": livraison_id, "nom_entreprise": nom,
                       "statut": "en_cours", "note": "Suis l'avancement avec details_entreprise."},
                      ensure_ascii=False)


async def _forge_capacites(client: httpx.AsyncClient, registre) -> str:
    """Agrège /capacites + /sante de l'adaptateur Forge (lecture seule).

    Dégrade proprement si Forge est down : message clair, jamais de stacktrace —
    l'assistant doit pouvoir dire « Forge est hors ligne » plutôt que planter.
    """
    base = _base(registre, "forge")
    try:
        rc = await client.get(f"{base}/capacites", timeout=6)
    except httpx.HTTPError:
        return json.dumps({
            "en_ligne": False,
            "message": "La brique Forge est injoignable (hors ligne ou en cours de démarrage).",
        }, ensure_ascii=False)
    if rc.status_code >= 400:
        return json.dumps({
            "en_ligne": False,
            "message": f"Forge a répondu en erreur (HTTP {rc.status_code}).",
        }, ensure_ascii=False)

    capas = rc.json()
    # Santé agrégée (tolérante : on garde les capacités même si /sante échoue).
    sante = {"statut": "inconnu"}
    try:
        rs = await client.get(f"{base}/sante", timeout=6)
        sante = rs.json() if rs.status_code < 400 else {"statut": "degrade"}
    except httpx.HTTPError:
        sante = {"statut": "injoignable"}

    return json.dumps({
        "en_ligne": bool(capas.get("core_en_ligne")),
        "sante": sante.get("statut"),
        "capacites": capas.get("capacites", []),
        "note": capas.get("note"),
    }, ensure_ascii=False)


async def _forge_appel(client: httpx.AsyncClient, registre, methode: str, chemin: str,
                       charge: dict | None = None, params: dict | None = None,
                       timeout: float = 30) -> str:
    """Appelle une route fonctionnelle de l'adaptateur Forge (S17) et renvoie une

    chaîne pour le LLM. Dégrade proprement (jamais de stacktrace) : Forge hors ligne,
    auth de service absente ou core en erreur → message clair que l'assistant peut
    relayer. L'auth machine-à-machine est gérée *dans* l'adaptateur Forge.
    """
    base = _base(registre, "forge")
    try:
        r = await client.request(methode, f"{base}{chemin}", json=charge, params=params,
                                  timeout=timeout)
    except httpx.HTTPError:
        return json.dumps({"ok": False,
                           "message": "La brique Forge est injoignable (hors ligne ou en démarrage)."},
                          ensure_ascii=False)
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except Exception:  # noqa: BLE001
            detail = r.text[:200]
        return json.dumps({"ok": False,
                           "message": f"Forge n'a pas pu traiter la demande (HTTP {r.status_code}) : {detail}"},
                          ensure_ascii=False)
    return json.dumps(r.json(), ensure_ascii=False)


async def _studio_appel(client: httpx.AsyncClient, registre, methode: str, chemin: str,
                        charge: dict | None = None, params: dict | None = None,
                        timeout: float = 60) -> str:
    """Appelle la brique Studio (audio-séries) et renvoie une chaîne pour le LLM.

    S'authentifie avec le « compte Studio » = la clé de service `STUDIO_KEY` (en-tête
    `X-API-Key`), si elle est configurée ; sinon la brique est en mode ouvert. Dégrade
    proprement (jamais de stacktrace) : brique hors ligne, 401 ou erreur → message clair.
    La production d'épisode appelle des LLM : timeout généreux par défaut.
    """
    base = _base(registre, "studio")
    cle = os.environ.get("STUDIO_KEY", "").strip()
    entetes = {"X-API-Key": cle} if cle else None
    try:
        r = await client.request(methode, f"{base}{chemin}", json=charge, params=params,
                                  headers=entetes, timeout=timeout)
    except httpx.HTTPError:
        return json.dumps({"ok": False,
                           "message": "La brique Studio est injoignable (hors ligne ou en démarrage)."},
                          ensure_ascii=False)
    if r.status_code == 401:
        return json.dumps({"ok": False,
                           "message": "Le Studio a refusé l'accès (clé de service absente ou invalide). "
                                      "Vérifie que STUDIO_KEY est bien la même côté noyau et côté brique."},
                          ensure_ascii=False)
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except Exception:  # noqa: BLE001
            detail = r.text[:200]
        return json.dumps({"ok": False,
                           "message": f"Le Studio n'a pas pu traiter la demande (HTTP {r.status_code}) : {detail}"},
                          ensure_ascii=False)
    # 204 (suppression) ou corps vide → succès sans payload.
    if r.status_code == 204 or not r.content:
        return json.dumps({"ok": True}, ensure_ascii=False)
    return json.dumps(r.json(), ensure_ascii=False)


async def _personnages_appel(client: httpx.AsyncClient, registre, methode: str, chemin: str,
                             charge: dict | None = None, params: dict | None = None,
                             timeout: float = 45, brut: bool = False):
    """Appelle la brique Personnages (5900, atelier holistique). Auth via `PERSONNAGES_KEY`
    (X-API-Key) si configurée ; sinon mode ouvert. Dégrade proprement (jamais de stacktrace).
    `brut=True` renvoie le dict parsé (pour chaîner géo→portrait→fiche)."""
    try:
        base = _base(registre, "personnages")
    except RuntimeError:
        msg = {"ok": False, "message": "La brique Personnages (atelier cosmique) est absente du registre du noyau."}
        return msg if brut else json.dumps(msg, ensure_ascii=False)
    cle = os.environ.get("PERSONNAGES_KEY", "").strip()
    entetes = {"X-API-Key": cle} if cle else None
    erreur = None
    try:
        r = await client.request(methode, f"{base}{chemin}", json=charge, params=params,
                                  headers=entetes, timeout=timeout)
        if r.status_code == 401:
            erreur = {"ok": False, "message": "Personnages a refusé l'accès (PERSONNAGES_KEY)."}
        elif r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except Exception:  # noqa: BLE001
                detail = r.text[:200]
            erreur = {"ok": False, "message": f"Personnages HTTP {r.status_code} : {detail}"}
        else:
            data = r.json() if r.content else {"ok": True}
            return data if brut else json.dumps(data, ensure_ascii=False)
    except httpx.HTTPError:
        erreur = {"ok": False,
                  "message": "La brique Personnages (atelier cosmique) est injoignable (hors ligne ou en démarrage)."}
    return erreur if brut else json.dumps(erreur, ensure_ascii=False)


def _empreinte_lignes(empreinte: list) -> list:
    """Aplati l'empreinte holistique ([{cle, valeur, …}]) en lignes lisibles (max 20)."""
    lignes = []
    for e in empreinte or []:
        if isinstance(e, dict):
            cle, val = str(e.get("cle") or "").strip(), str(e.get("valeur") or "").strip()
            ligne = f"{cle} : {val}" if cle and val else (cle or val)
        else:
            ligne = str(e).strip()
        if ligne:
            lignes.append(ligne)
    return lignes[:20]


async def _personnage_holistique(client: httpx.AsyncClient, registre, args: dict) -> str:
    """Crée un personnage holistique (brique 5900) depuis des infos de naissance dictées.

    Génération seule = non destructif (le portrait est déterministe, rien n'est stocké).
    Avec `enregistrer`/`serie_id` = action gardée par `confirme` : on enregistre la fiche
    et/ou on l'importe dans une série du Studio (nom de scène, nom cosmique d'origine gardé).
    Dégrade proprement si une brique est injoignable."""
    prenoms = (args.get("prenoms") or "").strip()
    date_naissance = (args.get("date_naissance") or "").strip()
    if not prenoms or not date_naissance:
        return json.dumps({"ok": False,
                           "message": "Il faut au moins des prénoms et une date de naissance (AAAA-MM-JJ)."},
                          ensure_ascii=False)
    enregistrer = bool(args.get("enregistrer"))
    serie_id = (args.get("serie_id") or "").strip()
    action = enregistrer or bool(serie_id)
    if action and not args.get("confirme"):
        cible = prenoms + (f" → série {serie_id}" if serie_id else " (enregistrer)")
        return _confirmation("créer et ranger le personnage cosmique", cible)

    nom_famille = (args.get("nom") or "").strip()
    nom_complet = (prenoms + (" " + nom_famille if nom_famille else "")).strip()
    ville = (args.get("ville") or "").strip()

    # Géocodage de la ville (optionnel) → latitude / longitude EST-positive
    latitude = longitude = None
    ville_resolue = ville
    if ville:
        g = await _personnages_appel(client, registre, "GET", "/geo",
                                     params={"ville": ville}, timeout=20, brut=True)
        if isinstance(g, dict) and g.get("latitude") is not None:
            latitude, longitude = g.get("latitude"), g.get("longitude")
            ville_resolue = g.get("ville") or ville

    # Portrait cosmique (déterministe — ne stocke rien)
    fiche_in = {"prenoms": prenoms, "nom": nom_famille, "date_naissance": date_naissance,
                "heure_naissance": args.get("heure_naissance") or None,
                "latitude": latitude, "longitude": longitude,
                "utc_offset": args.get("utc_offset")}
    portrait = await _personnages_appel(client, registre, "POST", "/holistique/portrait",
                                        charge=fiche_in, timeout=45, brut=True)
    if not isinstance(portrait, dict) or not portrait.get("portrait"):
        return json.dumps(portrait if isinstance(portrait, dict)
                          else {"ok": False, "message": "Portrait indisponible."}, ensure_ascii=False)

    p = portrait.get("portrait") or {}
    resume = {"ok": True, "prenoms": prenoms, "nom": nom_famille or None,
              "archetype": p.get("archetype"), "forces": p.get("forces"),
              "a_travailler": p.get("faiblesse"),
              "pierre": (p.get("pierre_equilibrage") or {}).get("pierre"),
              "ville": ville_resolue or None}
    if not action:
        return json.dumps(resume, ensure_ascii=False)

    # — Action confirmée : enregistrer et/ou importer dans une série du Studio —
    fiche_id = None
    if enregistrer:
        contexte = {"prenoms": prenoms, "nom": nom_famille, "date": date_naissance,
                    "heure": args.get("heure_naissance") or "", "ville": ville_resolue,
                    "latitude": latitude, "longitude": longitude}
        f = await _personnages_appel(client, registre, "POST", "/fiches", charge={
            "nom": nom_complet, "contexte": contexte,
            "traditions": portrait.get("traditions"), "portrait": p,
            "empreinte": portrait.get("empreinte")}, timeout=30, brut=True)
        if isinstance(f, dict) and f.get("id"):
            resume["fiche_enregistree"] = fiche_id = f["id"]
        else:
            resume["enregistrement"] = f  # message d'échec honnête

    if serie_id:
        nom_scene = (args.get("nom_scene") or "").strip()
        if fiche_id:   # fiche persistée → import par id (le Studio relit la fiche complète)
            imp = await _studio_appel(client, registre, "POST",
                                      f"/series/{serie_id}/personnages/importer-fiche",
                                      charge={"fiche_id": fiche_id, "nom": nom_scene or None},
                                      timeout=30)
        else:          # pas enregistrée → push direct (nom d'origine + archétype + empreinte)
            imp = await _studio_appel(client, registre, "POST",
                                      f"/series/{serie_id}/personnages/importer",
                                      charge={"nom": nom_scene or prenoms,
                                              "nom_naissance": nom_complet,
                                              "archetype": p.get("archetype"),
                                              "empreinte": _empreinte_lignes(portrait.get("empreinte")),
                                              "source": "personnages"}, timeout=30)
        try:
            resume["importe_dans_serie"] = json.loads(imp)
        except (ValueError, TypeError):
            resume["importe_dans_serie"] = imp
    return json.dumps(resume, ensure_ascii=False)


async def _transcription_appel(client: httpx.AsyncClient, registre, methode: str, chemin: str,
                               charge: dict | None = None, params: dict | None = None,
                               timeout: float = 60, brut: bool = False):
    """Appelle la brique Transcription (5980). S'authentifie avec `TRANSCRIPTION_KEY`
    (en-tête `X-API-Key`) si configurée ; sinon mode ouvert. Dégrade proprement (jamais de
    stacktrace). `brut=True` renvoie le dict parsé (pour chaîner transcrire→résumer) ;
    sinon une chaîne JSON pour le LLM. La transcription locale peut être lente : timeout large."""
    base = _base(registre, "transcription")
    cle = os.environ.get("TRANSCRIPTION_KEY", "").strip()
    entetes = {"X-API-Key": cle} if cle else None
    erreur = None
    try:
        r = await client.request(methode, f"{base}{chemin}", json=charge, params=params,
                                  headers=entetes, timeout=timeout)
        if r.status_code == 401:
            erreur = {"ok": False, "message": "Transcription a refusé l'accès (TRANSCRIPTION_KEY)."}
        elif r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except Exception:  # noqa: BLE001
                detail = r.text[:200]
            erreur = {"ok": False, "message": f"Transcription HTTP {r.status_code} : {detail}"}
        else:
            data = r.json() if r.content else {"ok": True}
            return data if brut else json.dumps(data, ensure_ascii=False)
    except httpx.HTTPError:
        erreur = {"ok": False,
                  "message": "La brique Transcription est injoignable (hors ligne ou en démarrage)."}
    return erreur if brut else json.dumps(erreur, ensure_ascii=False)


async def _etat_briques(client: httpx.AsyncClient, registre) -> dict:
    briques = []
    for nom, manifest in registre.briques.items():
        entree = {"nom": nom, "role": manifest.get("role"), "sante": "inconnu"}
        # Chemin de santé propre à chaque brique (certaines exposent /health, d'autres /sante) :
        # on dérive le chemin de l'url_sante du manifest, et l'hôte du registre.
        url_sante = manifest.get("url_sante") or ""
        chemin = "/" + url_sante.split("/", 3)[-1] if url_sante.count("/") >= 3 else "/sante"
        try:
            r = await client.get(f"{_base(registre, nom)}{chemin}", timeout=4)
            entree["sante"] = "ok" if r.status_code < 400 else "inaccessible"
        except Exception:
            entree["sante"] = "inaccessible"
        briques.append(entree)
    return {"briques": briques, "total": len(briques)}
