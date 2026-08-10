# Design — ROI chiffré + cahier des charges exportable (sprint 3/4 de la capacité « Audit d'entreprise → conception de solutions »)

**Date** : 2026-08-10
**Statut** : validé, prêt pour plan d'implémentation

## Contexte

Troisième des 4 sprints (ordre validé : entité → entretien → **ROI/CDC** → connecteurs).
Indépendant des sprints 1/2 en termes de code (pas de dépendance dure), mais plus utile une
fois l'entretien guidé (sprint 2) alimenté — plus de matière dans `profil_entreprise` et le
transcript processus, plus le chiffrage est pertinent.

Une revue de code a établi que `briques/audit` (5300) produit déjà des % (Pareto :
impact/fréquence, Territoire : `repartition_ca[].temps_pct`) mais **aucune conversion en
heures ou en euros**. La vision insiste explicitement : « le système ne doit surtout pas
inventer des économies certaines » — toute estimation doit être marquée comme telle.

Clarifications actées avec l'utilisateur pendant le brainstorming :
- Le calcul ROI devient une **5e couche de `briques/audit`** (Territoire/Flux/Problèmes/
  Priorités existent déjà ; ROI complète la même chaîne), pas un ajout à `generateur` — audit
  possède déjà toute la matière première (Pareto, `repartition_ca`).
- Le coût horaire nécessaire au calcul (Temps × Fréquence × Coût horaire) est, **par choix
  explicite de l'utilisateur**, proposé par le LLM comme fourchette plausible si le client ne
  le fournit pas — jamais bloquant. Contrepartie actée : chaque valeur produite porte un champ
  `statut` (`"fourni_client"` vs `"hypothese_llm"`) et un message de non-garantie, affiché à
  chaque endroit où le chiffre apparaît (JSON, cahier des charges, éventuel PPTX).
- Le **cahier des charges formel** est généré dans `briques/generateur` (qui lit déjà l'audit
  en entier pour construire son prompt d'app) plutôt que dans Forge — évite de dupliquer
  l'accès aux 4+1 couches de l'audit. Rendu PDF via `briques/export` (6150, thème `rapport`,
  déjà utilisé par Forge pour des « deck client »).

## État constaté du code (vérifié, pas supposé)

- `briques/audit/main.py:38-46` (table `audits`) : colonnes `territoire`, `flux`, `problemes`,
  `priorites` (TEXT JSON). Pas de colonne `roi`.
- `briques/audit/prompts.py::prompt_problemes` : la couche Pareto retourne, pour chaque
  problème, un impact en % et une fréquence en % (pas d'heures ni d'euros).
- `briques/audit/prompts.py::prompt_territoire` : `repartition_ca[].temps_pct` — part
  ESTIMÉE du temps de travail que chaque activité consomme (déjà une estimation d'expert
  assumée dans le prompt existant, précédent direct pour le ton « hypothèse » du ROI).
- `briques/audit/prompts.py::prompt_priorites` : la couche MoSCoW classe déjà les
  fonctionnalités à générer (Must/Should/Could/Won't) — matière directement réutilisable pour
  la section « fonctionnalités » du cahier des charges.
- `briques/generateur/main.py:26` (`AUDIT_URL`), `main.py:385-390`
  (`_charger_audit(audit_id)` → `GET {AUDIT_URL}/audits/{audit_id}`) : pont déjà existant et
  utilisé (`main.py:243-246`, `generer()`) pour construire le prompt de génération d'app —
  même pont à réutiliser pour charger territoire/flux/problemes/priorites/roi avant de
  structurer le CDC.
- `briques/export/manifest.json` : `POST /pdf` (`{titre, markdown, theme}`, thèmes `livre`/
  `rapport`), `POST /pptx` (`{titre, diapositives, theme}`) — déterministe (WeasyPrint/
  python-pptx), aucune IA, `confirme=true` requis (écrit un fichier). Déjà consommé par Forge
  pour des decks client — précédent direct pour un usage similaire ici.

## Architecture

### 1. `briques/audit` — 5e couche `roi`

- Colonne `roi TEXT` (JSON) ajoutée à `audits`, même motif que les 4 colonnes existantes.
- `POST /audits/{id}/chiffrer {cout_horaire?: {commercial?, production?, administratif?}}` —
  paramètre optionnel. Pour chaque problème de la couche Pareto :
  - temps mensuel estimé = combine `frequence` (Pareto) avec `repartition_ca[].temps_pct`
    (Territoire) de l'activité concernée ;
  - coût horaire = celui fourni par le client pour le pôle concerné, sinon une fourchette
    proposée par le LLM (`{bas, moyen, haut}`) ;
  - `cout_actuel_estime` = temps × coût horaire (fourchette basse/haute si coût hypothèse) ;
  - `gain_potentiel_estime` = `cout_actuel_estime` − coût après automatisation (estimé par le
    LLM à partir de la complexité de la solution proposée dans Priorités/MoSCoW).
  - **Chaque entrée porte** : `"statut": "fourni_client" | "hypothese_llm"` et
    `"avertissement": "Estimation à valider avec le client — non contractuelle."` (texte fixe,
    pas généré par le LLM, pour garantir qu'il est toujours présent mot pour mot).
- Statut `roi_indisponible` sur l'audit si le calcul échoue (LLM injoignable ou JSON
  incohérent) — jamais bloquant pour le reste de l'audit ni pour la génération d'app.

### 2. `briques/generateur` — cahier des charges

- `POST /audits/{id}/cahier-des-charges` : charge l'audit complet (`_charger_audit`, motif
  existant `main.py:385-390`), structure via LLM un document markdown avec les sections :
  objectifs, utilisateurs, fonctionnalités (depuis MoSCoW), règles métier, architecture, API,
  base de données, interfaces, intégrations, sécurité, tests, critères d'acceptation, **et une
  section ROI qui reprend telle quelle chaque entrée `roi` de l'audit avec son avertissement**.
- Le document est stocké (nouvelle table `cahiers_des_charges` dans `generateur`, ou colonne
  sur la table `apps` existante — à trancher en plan d'implémentation selon le schéma réel).
- `POST {EXPORT_URL}/pdf {titre, markdown, theme: "rapport"}` → PDF téléchargeable, exposé via
  un endpoint `GET /audits/{id}/cahier-des-charges/pdf`.
- Le **même markdown structuré** remplace le mélange informel actuel de
  territoire/flux/problemes/priorites dans `prompt_plan_app` — la génération d'app (`main.py`
  `generer()`) devient traçable à un document réel et relisable, pas seulement à un prompt
  interne.
- Bonus optionnel (même sprint, même effort marginal) : `POST {EXPORT_URL}/pptx` avec une
  version « points clés » du CDC (5-8 diapositives : problèmes majeurs, ROI, solution
  proposée, priorités) — réutilise le pattern déjà en place pour les decks client de Forge.

## Modèle de données

```sql
-- briques/audit
ALTER TABLE audits ADD COLUMN roi TEXT;

-- briques/generateur (nom de table à confirmer en plan selon le schéma existant)
CREATE TABLE IF NOT EXISTS cahiers_des_charges (
    id TEXT PRIMARY KEY,
    audit_id TEXT NOT NULL,
    markdown TEXT NOT NULL,
    pdf_chemin TEXT,
    statut TEXT NOT NULL DEFAULT 'genere',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cdc_audit ON cahiers_des_charges(audit_id);
```

## Erreurs / dégradation

- Chiffrage LLM échoue (`POST /audits/{id}/chiffrer`) : `roi=null` sur l'audit, statut
  `roi_indisponible`, endpoint retourne 200 avec ce statut plutôt qu'une erreur bloquante — le
  reste de l'audit (déjà `termine`) n'est jamais remis en cause.
- CDC généré sans ROI disponible : la section ROI du document affiche explicitement
  « Chiffrage non disponible — relancer `/chiffrer` » plutôt que d'être omise silencieusement
  ou de contenir un chiffre halluciné.
- `briques/export` injoignable au moment du PDF : le markdown reste stocké et consultable tel
  quel (`GET /audits/{id}/cahier-des-charges` renvoie le texte), `pdf_chemin` reste `null`,
  retry possible sans regénérer le contenu LLM (coût évité).
- Le texte d'avertissement (« Estimation à valider… ») est un **littéral fixe côté code**,
  jamais généré par le LLM — évite qu'un prompt malmené le fasse disparaître.

## Tests

- `briques/audit` : `POST /chiffrer` avec `cout_horaire` fourni (statut `fourni_client`,
  calcul déterministe vérifiable) ; sans `cout_horaire` (statut `hypothese_llm`, présence
  systématique de l'avertissement, mock LLM) ; échec LLM (statut `roi_indisponible`, audit
  reste `termine`).
- `briques/generateur` : génération CDC (mock `AUDIT_URL`, vérifie les 12 sections présentes
  + section ROI avec avertissement si `roi_indisponible`) ; export PDF (mock `EXPORT_URL`,
  succès et panne) ; non-régression de `generer()` (le prompt d'app utilise le CDC structuré,
  sortie de app-plan toujours valide sur un audit de test existant).
- Test explicite et permanent : **toute sortie ROI (JSON, markdown, PPTX) contient le texte
  d'avertissement mot pour mot** — garde-fou contre une régression qui ferait disparaître la
  mise en garde de la vision.

## Hors périmètre (explicitement)

- **Saisie du coût horaire dans l'entretien guidé** (sprint 2) — non re-ouvert dans ce sprint ;
  le paramètre `cout_horaire` de `/chiffrer` reste un appel manuel/API pour l'instant, le lien
  avec le squelette qualitatif de l'entretien est une amélioration future si besoin.
- **Mesure du ROI réel après déploiement** (comparaison avec la mesure d'usage déjà existante
  dans `briques/generateur/revue.py`, S31/S33) — hors périmètre, la boucle `revue.py` existante
  n'est pas modifiée par ce sprint.
- **UI de visualisation du CDC/ROI** — capacités API + export PDF/PPTX seulement.
- **Validation/signature du CDC par le client** — reste un échange humain hors Workplace dans
  ce sprint.
