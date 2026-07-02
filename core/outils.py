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
import catalogue
import conscience
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
        "name": "mes_capacites",
        "description": "Décris-toi JUSTE : ta propre anatomie (tes organes/briques) et la "
                       "liste exacte de tes outils. À appeler AVANT de répondre à « que sais-tu "
                       "faire ? », « qui es-tu ? », « comment es-tu fait ? » — réponds depuis ce "
                       "résultat, n'invente aucun organe ni pouvoir. Lecture seule.",
        "parameters": _p({}, [])}},
    {"type": "function", "function": {
        "name": "coagent_lancer",
        "description": "Lance un CO-AGENT autonome (ton « lobe frontal ») pour mener un "
                       "objectif MULTI-ÉTAPES en profondeur, sans repasser par l'utilisateur à "
                       "chaque étape (ex. « fais le tour de toutes les entreprises et propose un "
                       "plan », « croise les documents et l'agenda pour préparer la semaine »). Il "
                       "travaille en LECTURE SEULE (il observe, il n'agit pas) et rend une "
                       "SYNTHÈSE. Réserve-le aux tâches qui demandent plusieurs consultations "
                       "enchaînées ; pour une question simple, réponds directement.",
        "parameters": _p({
            "objectif": {"type": "string", "description": "L'objectif précis à mener à terme, en une phrase claire."},
            "budget_tokens": {"type": "integer", "description": "Plafond de tokens pour borner le coût (optionnel ; défaut raisonnable)."},
            "max_etapes": {"type": "integer", "description": "Plafond d'étapes de réflexion (optionnel)."},
        }, ["objectif"])}},
    {"type": "function", "function": {
        "name": "amelioration_etat",
        "description": "Où en est ton AUTO-AMÉLIORATION (S69/S70). Renvoie l'addendum de "
                       "prompt ACTIF, les propositions d'amélioration de prompt en attente "
                       "(avec statut et id) et les brouillons de CAPACITÉS proposés par le "
                       "Curator. À appeler avant « où en est ton amélioration ? », « as-tu "
                       "des propositions à valider ? » et AVANT toute décision (pour "
                       "récupérer les id). Lecture seule.",
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
            "rappels": {"type": "array", "items": {"type": "integer"},
                        "description": "Rappels = liste de MINUTES AVANT le début. Convertis le langage : « à l'heure »=0, « 10 min avant »=10, « 30 min avant »=30, « 1 h avant »=60, « la veille / 1 jour avant »=1440, « 1 semaine avant »=10080. Plusieurs possibles, ex. « 30 min avant et la veille »=[30,1440]. Omettre = aucun rappel."},
        }, ["titre", "debut", "fin"])}},
    {"type": "function", "function": {
        "name": "agenda_definir_rappels",
        "description": "Définit/modifie les rappels d'un événement EXISTANT (effet immédiat, pas de confirmation). Retrouve d'abord l'event_id via agenda_consulter. Remplace la liste complète ; passe une liste VIDE [] pour retirer tous les rappels.",
        "parameters": _p({
            "event_id": {"type": "string"},
            "rappels": {"type": "array", "items": {"type": "integer"},
                        "description": "Liste de MINUTES AVANT le début (0=à l'heure, 10, 30, 60=1h, 1440=1j, 10080=1sem). Liste vide = aucun rappel."},
        }, ["event_id", "rappels"])}},
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
        "name": "timetree_etat",
        "description": "État du pont TimeTree : connecté ? quel calendrier partagé est synchronisé ? À consulter avant de connecter ou synchroniser.",
        "parameters": _p({}, [])}},
    {"type": "function", "function": {
        "name": "timetree_connecter",
        "description": "Connecte le compte TimeTree (lecture seule, NON OFFICIEL) pour rapatrier l'agenda partagé. Demande l'email et le mot de passe TimeTree. ASTUCE : il vaut mieux le faire depuis le dashboard que par message (le mot de passe transite dans la conversation). Renvoie la liste des calendriers ; ensuite, choisis-en un via timetree_choisir_calendrier. ACTION (manipule un secret) : confirme=true requis après accord.",
        "parameters": _p({
            "email": {"type": "string", "description": "Email du compte TimeTree."},
            "password": {"type": "string", "description": "Mot de passe TimeTree."},
            "calendar_id": {"type": "string", "description": "Id du calendrier partagé à synchroniser (optionnel ; sinon choisir après)."},
            "confirme": {"type": "boolean"},
        }, ["email", "password"])}},
    {"type": "function", "function": {
        "name": "timetree_choisir_calendrier",
        "description": "Choisit le calendrier partagé TimeTree à synchroniser (via un id obtenu de timetree_connecter / timetree_etat).",
        "parameters": _p({
            "calendar_id": {"type": "string"},
        }, ["calendar_id"])}},
    {"type": "function", "function": {
        "name": "timetree_synchroniser",
        "description": "Lance une synchronisation TimeTree → Workplace (pull lecture seule de l'agenda partagé vers le calendrier « TimeTree »). Effet immédiat.",
        "parameters": _p({}, [])}},
    {"type": "function", "function": {
        "name": "timetree_deconnecter",
        "description": "Déconnecte TimeTree et purge les identifiants du coffre (révocation). ACTION : confirme=true requis après accord.",
        "parameters": _p({
            "confirme": {"type": "boolean"},
        }, [])}},
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
        "name": "personnages_fiches_lister",
        "description": "Liste les personnages holistiques ENREGISTRÉS dans l'atelier (brique 5900). Renvoie id, nom, catégorie et archétype de chaque fiche. Lecture seule (aucune confirmation). Pour « mes personnages créés », « liste mes fiches », « quels personnages j'ai enregistrés ».",
        "parameters": _p({}, [])}},
    {"type": "function", "function": {
        "name": "personnage_importer_serie",
        "description": "Importe un personnage DÉJÀ ENREGISTRÉ dans l'atelier holistique vers une série du Studio. Récupère fiche_id via personnages_fiches_lister et serie_id via studio_series_lister. ACTION : confirme=true requis après accord.",
        "parameters": _p({
            "fiche_id": {"type": "string", "description": "Id de la fiche holistique (via personnages_fiches_lister)."},
            "serie_id": {"type": "string", "description": "Id de la série cible (via studio_series_lister)."},
            "nom_scene": {"type": "string", "description": "Nom de scène dans la série (optionnel : défaut = nom de la fiche)."},
            "confirme": {"type": "boolean"},
        }, ["fiche_id", "serie_id"])}},
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
    # — AUTO-AMÉLIORATION (S75) : piloter le cycle S68→S70 en conversation —
    {"type": "function", "function": {
        "name": "curateur_lancer",
        "description": "Lance MAINTENANT un cycle de curation (normalement hebdomadaire) : "
                       "tu te mesures (proprioception) puis tu PROPOSES — sans rien appliquer "
                       "— une amélioration de ton prompt et un brouillon de capacité "
                       "manquante, et tu déposes un digest 🔔. Pour « améliore-toi », « fais "
                       "un tour de curation ». Coûte un peu de calcul. ACTION : confirme=true "
                       "requis après accord.",
        "parameters": _p({"confirme": {"type": "boolean"}}, [])}},
    {"type": "function", "function": {
        "name": "amelioration_evaluer",
        "description": "A/B honnête sur une proposition d'amélioration de prompt : rejoue des "
                       "questions avec/sans l'addendum et note les deux pour éclairer la "
                       "décision. Récupère l'id via amelioration_etat. Coûte du calcul. "
                       "ACTION : confirme=true requis après accord.",
        "parameters": _p({"id": {"type": "string"}, "confirme": {"type": "boolean"}}, ["id"])}},
    {"type": "function", "function": {
        "name": "amelioration_decider",
        "description": "Tranche sur une proposition d'amélioration de PROMPT (le gate humain). "
                       "decision = 'valider' (approuve sans activer), 'appliquer' (active "
                       "vraiment l'addendum → change ton comportement ; vaut "
                       "validation+activation), 'rejeter' (écarte), 'desactiver' (revient au "
                       "prompt fondateur, sans id). Récupère l'id via amelioration_etat. "
                       "ACTION : confirme=true requis après accord.",
        "parameters": _p({
            "decision": {"type": "string", "enum": ["valider", "appliquer", "rejeter", "desactiver"]},
            "id": {"type": "string", "description": "id de la proposition (inutile pour desactiver)."},
            "confirme": {"type": "boolean"},
        }, ["decision"])}},
    {"type": "function", "function": {
        "name": "capacite_decider",
        "description": "Tranche sur un BROUILLON de capacité proposé par le Curator. decision "
                       "= 'retenir' (le garder comme SPÉCIFICATION à implémenter par une "
                       "brique — ça n'active AUCUN outil, c'est honnête) ou 'rejeter'. "
                       "Récupère l'id via amelioration_etat. ACTION : confirme=true requis "
                       "après accord.",
        "parameters": _p({
            "decision": {"type": "string", "enum": ["retenir", "rejeter"]},
            "id": {"type": "string"},
            "confirme": {"type": "boolean"},
        }, ["decision", "id"])}},
]

OUTILS_ACTION = {
    "livrer_entreprise", "decrocher_entreprise", "reprendre_entreprise",
    "ingerer_document", "classer_document", "creer_enregistrement", "memoire_retenir",
    "agenda_supprimer_evenement", "agenda_inviter",
    "timetree_connecter", "timetree_deconnecter",
    "forge_rag_ingerer", "forge_lancer_agent",
    "forge_facture_creer", "forge_facture_statut", "forge_facture_transformer",
    "forge_crm_creer", "forge_crm_modifier", "forge_paiement_lien",
    "forge_relances_envoyer", "forge_facture_envoyer",
    "studio_serie_creer", "studio_episode_produire", "studio_express",
    "studio_bible_decider", "studio_perso_creer", "studio_audio_produire",
    "transcription_archiver",
    "curateur_lancer", "amelioration_evaluer", "amelioration_decider", "capacite_decider",
}


_NOMS_STATIQUES = {o["function"]["name"] for o in OUTILS}
CAPACITES_DYNAMIQUES = os.getenv("CAPACITES_DYNAMIQUES", "1").lower() not in ("0", "false", "no")
_ALLOWLIST = {s.strip() for s in os.getenv("CAPACITES_ALLOWLIST", "").split(",") if s.strip()}

# ── La porte à divulgation progressive (S90) ─────────────────────────────────
# Pendant de `ToolSearch`/`Skill` de Claude Code : les capacités de NIVEAU ≥ 1 ne sont PAS
# présentées en entier au LLM (corps + schéma) — elles restent « derrière la porte », juste
# listées (nom + description) dans le méta-outil `competence_charger`. Le LLM appelle ce
# méta-outil avec le `nom` voulu : le schéma complet devient appelable au tour suivant. But :
# dégraisser le contexte (et le rendre cacheable) sans amputer les pouvoirs. OFF par défaut
# (`PORTE_PROGRESSIVE`) → tant qu'aucune capacité ne déclare `niveau: 1`, comportement S64
# strictement inchangé.
PORTE_PROGRESSIVE = os.getenv("PORTE_PROGRESSIVE", "0").lower() in ("1", "true", "yes", "on")
META_CHARGER = "competence_charger"


def _capacites_dynamiques(registre) -> dict:
    """Capacités découvertes qui deviennent des outils dynamiques : ``{nom: cap}``.

    N'expose JAMAIS un nom déjà câblé en dur (l'outil statique, plus riche, prime →
    zéro régression), respecte une éventuelle liste blanche ``CAPACITES_ALLOWLIST``, et
    s'éteint entièrement avec ``CAPACITES_DYNAMIQUES=0`` (repli honnête sur les seuls
    outils en dur). En cas de doublon inter-briques, le premier découvert gagne."""
    if not CAPACITES_DYNAMIQUES or registre is None:
        return {}
    out: dict = {}
    for cap in catalogue.collecter_capacites(registre):
        nom = cap["nom"]
        if nom in _NOMS_STATIQUES or nom in out:
            continue
        if _ALLOWLIST and nom not in _ALLOWLIST:
            continue
        out[nom] = cap
    return out


def _spec_depuis_capacite(cap: dict) -> dict:
    """Convertit une capacité du catalogue en spec function-calling OpenAI."""
    props: dict = {}
    requis: list = []
    for nom_p, p in (cap.get("params") or {}).items():
        props[nom_p] = {k: v for k, v in p.items() if k != "requis"}
        if p.get("requis"):
            requis.append(nom_p)
    if cap.get("action"):
        props.setdefault("confirme", {"type": "boolean",
            "description": "Passer true UNIQUEMENT après accord explicite de l'utilisateur."})
    return {"type": "function", "function": {
        "name": cap["nom"], "description": cap.get("description", ""),
        "parameters": _p(props, requis)}}


def _differees(registre, chargees) -> dict:
    """Capacités NIVEAU ≥ 1 encore derrière la porte (non chargées) : ``{nom: cap}``."""
    deja = set(chargees or ())
    return {n: c for n, c in _capacites_dynamiques(registre).items()
            if c.get("niveau", 0) >= 1 and n not in deja}


def _spec_charger(differees: dict) -> dict:
    """Méta-outil `competence_charger` : liste les compétences différées (nom — description)
    dans sa propre description et permet de charger l'une d'elles par son nom (pendant de
    `ToolSearch`). Présenté UNIQUEMENT s'il reste quelque chose derrière la porte."""
    catalogue_txt = " ; ".join(f"{n} — {c.get('description', '') or 'sans description'}"
                               for n, c in sorted(differees.items()))
    return {"type": "function", "function": {
        "name": META_CHARGER,
        "description": (
            "Charge une COMPÉTENCE différée pour pouvoir l'utiliser : son schéma complet "
            "devient appelable au tour SUIVANT. Appelle-moi avec le `nom` EXACT avant "
            "d'employer la compétence voulue. Compétences chargeables : "
            + catalogue_txt + "."),
        "parameters": _p({"nom": {"type": "string",
                                  "description": "Nom exact de la compétence à charger."}},
                         ["nom"])}}


def outils_pour(registre, *, chargees=None, porte: bool = False) -> list[dict]:
    """Liste d'outils présentée au LLM : les outils en dur + les capacités dynamiques.

    C'est la fin du contrat figé : ajouter `capacites` à un manifest suffit pour que
    l'assistant voie un nouvel outil, sans toucher au Cœur.

    `porte=True` (S90) active la divulgation progressive : les capacités de niveau ≥ 1 NON
    présentes dans `chargees` sont retirées et remplacées par le méta-outil `competence_charger`
    (qui les liste). `porte=False` (défaut, ex. Gateway MCP) renvoie TOUT — comportement S64.

    La liste est TRIÉE par nom dans les deux cas : préfixe d'outils stable d'une requête à
    l'autre → cacheable (S90a). Le tri ne change rien fonctionnellement (function-calling)."""
    dyn = _capacites_dynamiques(registre)
    specs = OUTILS + [_spec_depuis_capacite(c) for c in dyn.values()]
    if porte:
        differees = _differees(registre, chargees)
        if differees:
            specs = [s for s in specs if s["function"]["name"] not in differees]
            specs = specs + [_spec_charger(differees)]
    return sorted(specs, key=lambda s: s["function"]["name"])


def est_action(nom: str, registre) -> bool:
    """Outil à effet de bord ? (pastille « action » + gate de confirmation côté UI)."""
    if nom in OUTILS_ACTION:
        return True
    cap = _capacites_dynamiques(registre).get(nom)
    return bool(cap and cap.get("action"))


# ── Exécution : routage vers les dispatchers par domaine (S115) ──────────────────
import outils_domaines as _dom
# Ré-exports d'API attendus par les tests / autres modules (les helpers vivent dans communs).
from outils_communs import (  # noqa: F401
    _appel_dynamique, _studio_appel, _personnages_appel, _personnage_holistique,
)

_DISPATCHERS = (
    _dom.systeme.dispatch, _dom.amelioration.dispatch, _dom.documents.dispatch,
    _dom.agenda.dispatch, _dom.forge.dispatch, _dom.usine.dispatch,
    _dom.studio.dispatch, _dom.transcription.dispatch,
)


async def executer(nom: str, args: dict, registre) -> str:
    """Exécute un outil et renvoie une chaîne (résultat ou message) pour le LLM.

    On ouvre un client HTTP partagé, puis on interroge chaque dispatcher de domaine
    dans l'ordre ; le premier qui reconnaît `nom` renvoie une chaîne. À défaut, on
    tente une capacité dynamique (découverte par manifest, S64). Le filet d'erreurs
    (try/except) reste ici, centralisé, inchangé."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            for dispatch in _DISPATCHERS:
                res = await dispatch(nom, args, registre, client)
                if res is not None:
                    return res
            # — CAPACITÉS DYNAMIQUES (S64) : routées par le catalogue des manifests —
            cap = _capacites_dynamiques(registre).get(nom)
            if cap:
                return await _appel_dynamique(client, cap, args)
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
