def prompt_territoire(contexte: str) -> str:
    return f"""Voici les documents de l'entreprise :
{contexte}

Identifie et retourne un JSON avec exactement ces clés :
- "ddd" : un objet décrivant le domaine métier (Domain-Driven Design), avec :
    - "bounded_contexts" : liste des départements/fonctions, chacun avec :
        - "nom" : le nom du département tel que l'entreprise l'appelle (utilise SON vocabulaire, pas un terme générique)
        - "responsable" : le responsable si mentionné, sinon "—"
        - "langage_ubiquitaire" : liste de 3-5 termes du vocabulaire propre à ce département (les mots réels employés dans les documents)
    - "evenements_cles" : liste des événements qui déclenchent des actions, formulés avec les mots de l'entreprise (ex: "Bouquet commandé", "Dossier ouvert")
    - "agregats" : les objets métier principaux, nommés AVEC LE TERME DE L'ENTREPRISE (ex: "Composition florale" et non "Produit", "Dossier client" et non "Contrat")
- "glossaire_metier" : le cœur de l'analyse linguistique. Liste de 5 à 12 entrées, chacune avec :
    - "terme_generique" : le mot générique/standard (ex: "client", "produit", "commande", "facture", "employé")
    - "terme_entreprise" : le mot RÉELLEMENT employé par cette entreprise dans ses documents (ex: "adhérent", "composition", "réservation")
    - "definition" : une phrase courte expliquant ce que ce terme recouvre dans cette entreprise
  Ne mets QUE des termes réellement présents/déductibles des documents. Ce glossaire servira à adapter le vocabulaire de l'application livrée.
- "business_model_canvas" : les 9 blocs du BMC remplis avec ce que les docs permettent de déduire (proposition_valeur, segments_clients, canaux, relations_clients, flux_revenus, ressources_cles, activites_cles, partenaires_cles, structure_couts)
- "repartition_ca" : la décomposition du chiffre d'affaires par activité, gamme, segment de clients ou produit. Liste d'objets, un par activité, avec :
    - "libelle" : nom de l'activité/segment
    - "montant" : NOMBRE en euros (sans symbole ni espaces) si connu, sinon null
    - "pourcentage" : part du CA, NOMBRE de 0 à 100 si connu, sinon null
    - "temps_pct" : part ESTIMÉE du temps de travail / de l'occupation des équipes que cette activité consomme (NOMBRE de 0 à 100). Estime-le à partir de la complexité, du sur-mesure, du SAV et des délais décrits dans les documents — il est NORMAL que ce soit différent de la part de CA (une activité peut être chronophage mais peu rentable, ou l'inverse). La somme des temps_pct doit avoisiner 100.
    - "penibilite" : pénibilité/difficulté de l'activité pour les équipes, une valeur parmi "faible" | "moyenne" | "élevée", déduite de la complexité, des reprises SAV et des contraintes décrites.
  Pour montant et pourcentage : ne mets que ce qui est réellement déductible des documents (sinon null). temps_pct et penibilite sont des ESTIMATIONS d'expert assumées. Trie du plus gros contributeur de CA au plus petit. Si aucune décomposition n'est disponible, retourne une liste vide.
- "stakeholders" : les acteurs mentionnés avec leur rôle, niveau d'influence et d'intérêt (haute/moyenne/basse)
- "raci_resume" : pour chaque processus identifié, qui est Responsable, Approbateur, Consulté, Informé"""


def prompt_flux(contexte: str, territoire_json: str) -> str:
    return f"""Voici les documents de l'entreprise :
{contexte}

Contexte déjà analysé (territoire) :
{territoire_json}

Retourne un JSON avec :
- "value_stream_map" : les étapes séquentielles du flux de valeur principal, avec pour chaque étape le temps à valeur ajoutée estimé (en heures), le temps d'attente, l'acteur responsable. Calcule l'efficacité du flux en % (somme VA / somme totale * 100). Identifie les goulots.
- "sipoc" : pour le processus principal identifié (fournisseurs, entrants, processus_principal, sorties, clients)
- "processus_cles" : les 3-5 processus les plus importants avec leurs étapes, déclencheur, résultat
- "event_storming" : liste les événements domaine (passé composé : "Commande passée"), les commandes (impératif : "Passer commande"), les politiques (règles métier) et les vues lecture"""


def prompt_problemes(contexte: str, territoire_json: str, flux_json: str) -> str:
    return f"""Voici les documents de l'entreprise :
{contexte}

Territoire : {territoire_json}
Flux : {flux_json}

Retourne un JSON avec :
- "ishikawa" : identifie le problème central le plus critique, puis classe ses causes dans les 6M (main_oeuvre, methodes, machines, matieres, milieu, management)
- "pareto" : liste tous les problèmes identifiés, estime leur impact en % et leur fréquence en %. Identifie les 20% de causes qui génèrent 80% des effets. Formule une recommandation.
- "theory_of_constraints" : identifie le goulot principal qui limite TOUT le système (une seule contrainte à la fois), explique pourquoi c'est lui, et propose les 5 étapes d'élévation de Goldratt adaptées à ce contexte
- "cinq_pourquoi" : pour les 2-3 problèmes les plus importants, descends 5 niveaux de "pourquoi" pour atteindre la cause racine"""


def prompt_priorites(contexte: str, territoire_json: str, flux_json: str, problemes_json: str) -> str:
    return f"""Voici les documents de l'entreprise :
{contexte}

Territoire : {territoire_json}
Flux : {flux_json}
Problèmes : {problemes_json}

Retourne un JSON avec :
- "chemin_critique" : liste les tâches de transformation à mener (T1, T2...), leur durée estimée en jours, leurs dépendances (depends_de: ["T1"...]), et marque celles qui sont sur le chemin critique (est_critique: true). Calcule la durée totale du projet.
- "pert" : pour chaque tâche du chemin critique, donne 3 estimations (optimiste/probable/pessimiste), calcule l'espérance (o+4p+P)/6 et la variance ((P-o)/6)². Calcule la durée espérée totale et l'écart-type.
- "swot" : forces/faiblesses internes, opportunités/menaces externes — 3-5 points chacun
- "okrs_proposes" : propose 2-3 OKRs (Objectif + 2-3 Key Results mesurables avec valeur cible) en réponse aux problèmes identifiés
- "moscow" : classe les fonctionnalités à générer pour l'app sur-mesure : Must (indispensable), Should (important), Could (utile si le temps le permet), Won't (hors scope v1)"""


def prompt_roi(territoire_json: str, problemes_json: str, priorites_json: str,
               cout_horaire_json: str) -> str:
    return f"""Territoire (dont repartition_ca[].temps_pct) : {territoire_json}
Problèmes (dont pareto : impact %, fréquence %) : {problemes_json}
Priorités (dont moscow, chemin_critique) : {priorites_json}

Coût horaire connu du client par pôle (peut être vide) : {cout_horaire_json}

Pour CHAQUE problème listé dans pareto, chiffre son coût actuel et son gain potentiel après
automatisation. Combine sa fréquence (pareto) avec le temps_pct de l'activité concernée
(repartition_ca) pour estimer un temps mensuel en heures. Le coût après automatisation
s'appuie sur la complexité de la solution proposée dans moscow/chemin_critique.

Retourne un JSON avec exactement ces clés :
- "problemes" : liste d'objets, un par problème du pareto, chacun avec :
    - "probleme" : le libellé du problème (repris du pareto)
    - "pole" : "commercial" | "production" | "administratif" — le pôle métier concerné
    - "temps_mensuel_heures" : NOMBRE d'heures/mois estimées consommées par ce problème
    - "cout_horaire_estime" : SI le pôle n'est PAS dans le coût horaire connu du client,
      une fourchette {{"bas":NOMBRE,"moyen":NOMBRE,"haut":NOMBRE}} en euros/heure plausible
      pour ce type de poste ; sinon null (le coût horaire du client sera utilisé tel quel)
    - "cout_actuel_estime" : {{"bas":NOMBRE,"haut":NOMBRE}} en euros/mois (fourchette basse/haute)
    - "gain_potentiel_estime" : {{"bas":NOMBRE,"haut":NOMBRE}} en euros/mois après automatisation
- "synthese" : 1-2 phrases résumant le chiffrage global (ordre de grandeur, pas de total garanti)

N'invente jamais un coût horaire fourni par le client — utilise UNIQUEMENT ceux listés
ci-dessus ; pour les autres pôles, propose une fourchette réaliste et dis-le."""
