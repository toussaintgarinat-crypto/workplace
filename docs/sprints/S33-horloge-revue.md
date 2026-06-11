# Sprint S33 — Horloge sur la revue (« app vivante » périodique)

**Objectif** : rendre « l'app vivante » **autonome**. S31 propose un incrément, S32
l'applique — mais les deux étaient déclenchés à la main. S33 déclare la revue comme
**tâche périodique** dans le manifest du générateur : l'horloge S29 la découvre et
**balaye** régulièrement toutes les apps livrées au **consentement actif** pour proposer
un incrément. L'application (S32) reste, elle, **toujours** une décision humaine.

**Statut** : ✅ LIVRÉ CODE + **4 tests offline verts** + **PROUVÉ LIVE (dev)** le
2026-06-11 (déclenché de bout en bout par l'horloge du Cœur).

S'appuie sur : **horloge S29** (contrat `taches` du manifest), **revue S31** (mesure +
proposition), et préserve **S32** (valider → appliquer manuels).

---

## Ce qui a été construit

| Pièce | Rôle |
|---|---|
| `briques/generateur/manifest.json` | Déclare la tâche `revue-app-vivante` (`POST /revues/balayage`, `cadence_heures: 168`, `idempotent`, `tolere_echec`) — découverte automatiquement par l'horloge S29. |
| `briques/generateur/main.py` | `POST /revues/balayage` : parcourt **toutes** les apps, ne (re)propose que celles éligibles, best-effort (une app en erreur n'arrête pas le balayage). Renvoie `{balayees, proposees, ignorees, erreurs}`. Refactor : `_revue_app()` partagé par la revue manuelle (S31) et le balayage. |
| `briques/generateur/revue.py` | `doit_reviser(partage, revue_actuelle) -> (éligible, raison)` — règle d'éligibilité **pure** et testable. |
| `briques/generateur/test_balayage.py` | 4 scénarios offline (éligibilité + contrat manifest). |

## Décisions d'architecture

- **Souveraineté d'abord.** Le balayage ne mesure **que** les apps au consentement actif
  (`partage_forge.actif`). Sans consentement → app ignorée, aucune mesure, aucun appel
  réseau (cohérent avec S31).
- **L'humain garde la main (S31→S32 intacts).** Le balayage ne fait que **proposer**
  (statut `propose`). Il ne valide ni n'applique jamais. Et il **ne ré-propose pas
  par-dessus une revue `validee`** en attente d'application : on n'écrase pas une décision
  prise mais pas encore exécutée.
- **Best-effort.** Une app dont la revue échoue (donnees ou Gateway momentanément KO)
  est tracée dans `erreurs` sans interrompre le balayage des autres. `tolere_echec: true`
  côté manifest : un balayage partiel n'est pas une alarme.
- **Cadence hebdomadaire.** `168 h` : un re-audit a du sens à l'échelle de la semaine, pas
  du jour (contrairement au briefing S30, quotidien).
- **Fidèle au modèle noyau + briques.** Aucune logique de planification dans le
  générateur : il **déclare** sa tâche, l'horloge (Cœur) l'exécute — exactement comme les
  relances S22, la sync agenda S27 et le briefing S30.

## Le flux (bout en bout)

1. L'horloge S29 (boucle du Cœur) lit les manifests, découvre `generateur/revue-app-vivante`.
2. Cadence due → `POST http://generateur/revues/balayage` (self-call HTTP du Cœur).
3. Le générateur balaye : pour chaque app éligible, mesure consentie + proposition
   (statut `propose`). Les non-consentantes et les `validee` en attente sont sautées.
4. Le cabinet retrouve une proposition fraîche, qu'il **valide** (S31) puis **applique**
   (S32) quand il le décide.

## Tests

```
cd briques/generateur && python3 test_balayage.py
  ✅ 1. souveraineté : consentement inactif/absent → non éligible
  ✅ 2. respect humain : revue validée en attente → sautée (pas d'écrasement)
  ✅ 3. consentement actif + revue absente/appliquée/rejetée/propose → éligible
  ✅ 4. contrat manifest : tâche revue-app-vivante bien formée pour l'horloge
  4/4 scénarios OK
```
Non-régression : `test_revue.py` (5/5), `test_appliquer.py` (5/5), `test_pont_crm.py`
(6/6). `py_compile` OK. Aucune nouvelle dépendance.

## Preuve LIVE (dev) — 2026-06-11

Vraie stack : Cœur (5100) + `generateur` (5400) + `donnees` (5500) + Gateway (4001).

| Vérité prouvée | Observé LIVE |
|---|---|
| L'horloge **découvre** la tâche | `GET /horloge/taches` → `generateur / revue-app-vivante — cadence 168 h` (aux côtés de agenda/sync-google, forge/relances-impayes, noyau/briefing-quotidien) |
| L'horloge **déclenche** le balayage | `POST /horloge/executer?forcer=true&brique=generateur&tache=revue-app-vivante` → `statut: ok, code_http: 200` |
| Sélection correcte | `POST /revues/balayage` → 14 balayées : **1 proposée** (consentement actif, `source=llm`), **13 ignorées** (12 sans consentement + 1 `validee` en attente), **0 erreur** |
| Souveraineté | les 12 apps sans consentement ne sont jamais mesurées |
| Respect humain | l'app `validee` (S31) n'est pas ré-proposée (décision préservée) |

Conclusion : la revue « app vivante » est désormais **déclenchée par l'horloge** de bout en
bout, dans le strict respect du consentement et de la décision humaine.

## Dettes / suites

- **Notifier le cabinet** quand une nouvelle proposition est prête (rappel 🔔 comme le
  briefing S30, ou message Oria) — aujourd'hui le balayage est silencieux.
- **Cadence configurable par app** (certaines entreprises évoluent plus vite) — la
  cadence est globale (168 h) pour l'instant.
