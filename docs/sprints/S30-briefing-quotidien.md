# Sprint S30 — Briefing quotidien (Jarvis proactif)

**Objectif** : chaque matin, l'assistant **vient vers l'utilisateur** au lieu d'attendre
une question. Il rassemble ce qui compte — rendez-vous du jour, factures impayées à
relancer (J+7/15/30), pipeline commercial, coût LLM de la veille — et en **rédige une
synthèse** déposée dans la pastille 🔔 existante. C'est le comportement qui définit un
« Jarvis » : parler le premier.

**Statut** : ✅ LIVRÉ + 7 tests verts + **PROUVÉ LIVE (dev)** le 2026-06-10.

---

## Ce qui a été construit

| Pièce | Rôle |
|---|---|
| `core/briefing.py` | Collecte tolérante des 4 sources → synthèse par l'économe local → dépôt en rappel 🔔. Idempotent par jour. |
| `briques/noyau/manifest.json` | Déclare la tâche `briefing-quotidien` (cadence 24 h) à l'**horloge S29** — le noyau s'expose au registre uniquement pour ça. |
| `core/journal_usage.py` | `agregat_jour(date)` — coût LLM d'une date donnée (la « veille »), indépendant du jour courant. |
| `core/proactif.py` | `existe_cle` / `supprimer_cle` — idempotence par jour (un seul briefing par date, même lu) et régénération forcée (remplace, ne duplique pas). |
| `core/main.py` | `POST /briefing/executer` (déclenché par l'horloge ; `forcer=true` régénère) et `GET /briefing/dernier`. Rendu front : `white-space:pre-wrap` pour que la mise en forme du briefing survive. |
| `core/test_briefing.py` | 7 tests autonomes (httpx + LLM simulés, journaux isolés). |

## Décisions d'architecture

- **Fidèle au modèle noyau + briques.** Le briefing ne code en dur aucun planning : la
  tâche est **déclarée dans un manifest** (`noyau`) et découverte par l'horloge S29,
  exactement comme `relances-impayes` (forge) ou `sync-google` (agenda). Aucun cas
  particulier dans le planificateur.
- **L'horloge déclenche le cœur par son propre contrat HTTP** (self-call interne via
  `NOYAU_URL=http://127.0.0.1:5000`). C'est ce qui **prouve la dépendance S29→S30 de
  bout en bout** : l'horloge appelle `POST /briefing/executer` comme n'importe quelle
  brique.
- **Synthèse par l'économe local (S138).** La cascade cost-first met un modèle **gratuit
  en tête** → coût ~0. Le briefing est étiqueté `briefing` au journal d'usage.
- **Pas de nouveau canal.** Le briefing se dépose comme un **rappel proactif** (S12) et
  s'affiche dans la pastille 🔔 déjà connue de l'utilisateur.
- **Tolérant et honnête.** Chaque source en panne devient `{"indisponible": …}` ; la
  synthèse ignore silencieusement ce qu'elle ne sait pas (le prompt l'interdit
  d'inventer). Une synthèse impossible → aucun rappel vide n'est déposé.

## Preuve LIVE (dev, 2026-06-10)

Cœur reconstruit, **11 briques** chargées (noyau inclus), contre la vraie stack
(forge-adapter, gateway, agenda) :

1. **Horloge voit la tâche** : `GET /horloge/taches` liste `noyau/briefing-quotidien`,
   cadence 24 h → `/briefing/executer`.
2. **Briefing rédigé pour de vrai** : `POST /briefing/executer?forcer=true` →
   `statut: cree`, modèle **`free/openrouter/owl-alpha`** (gratuit), **coût `0.0 $`**.
   Les faits proviennent des vraies briques (la forme réelle de `/relances/apercu` —
   `a_relancer / total / montant_total / deja_relancees / ignorees` — est bien
   rapatriée), pipeline CRM réduit, coût LLM de la veille lu au journal.
3. **Visible dans la pastille 🔔** : `GET /assistant/rappels` → rappel de type
   `briefing` (« Briefing du Wednesday 10 June ») ; `GET /briefing/dernier` le renvoie.
4. **Idempotent** : 2ᵉ `POST /briefing/executer` sans `forcer` → `statut: deja_fait`
   (pas de doublon).
5. **Journalisé** : `GET /assistant/usage` → 1 appel du jour, coût `0.0 $`
   (l'économe gratuit).
6. **Déclenché par l'horloge** (S29→S30 bout en bout) :
   `POST /horloge/executer?forcer=true&brique=noyau&tache=briefing-quotidien` →
   `statut: ok, code_http: 200` ; le journal de l'horloge passe `nb_executions` à 2,
   `dernier_statut: ok` — l'horloge a bien appelé le contrat du cœur en self-call HTTP.

## Tests

```
cd core && python3 test_briefing.py
  ✓ test_collecter_assemble_les_quatre_sources
  ✓ test_collecter_tolere_forge_hors_ligne
  ✓ test_collecter_tolere_forge_absent_du_registre
  ✓ test_agregat_jour_filtre_par_date
  ✓ test_executer_depose_un_rappel_et_est_idempotent
  ✓ test_executer_forcer_regenere_sans_dupliquer
  ✓ test_executer_signale_un_echec_de_synthese
✅ TOUS LES TESTS PASSENT
```
Non-régression : `test_horloge.py` (7) et `test_s138.py` (8) verts.

## Dettes / suites

- **Message Oria** : le briefing est livré dans le chat 🔔 ; le « et/ou message Oria »
  du backlog (push vers l'app cliente) reste optionnel, non fait.
- **Fuseau du coût veille** : `agregat_jour` filtre sur les dates UTC du journal ; la
  « veille » est calculée en heure de Paris. Écart possible en bord de minuit —
  acceptable pour une ligne de coût, pas de la comptabilité.
- **Cadence vs heure fixe** : l'horloge déclenche « toutes les 24 h » depuis la 1ʳᵉ
  exécution, pas à une heure du matin garantie. Suffisant pour un briefing quotidien ;
  un créneau horaire précis serait une évolution du contrat `taches`.
- Débloque **S31 — « L'app vivante »** (re-audit post-livraison).
