# S245 — Socle d'approbation Telegram

Épopée : [livraison + support](EPOPEE-livraison-support-assistant.md). Statut : **CODÉ + REVU, preuve LIVE Telegram différée (SLIVE)**. ADR : `docs/decisions/2026-11-25-approbation-telegram.md`.
Dépend de : S222 (`core/accord_action.py`, ADR `docs/decisions/2026-08-09-gate-action-structurel.md`),
S76 (boutons), S77 (Mini App Telegram, `briques/connexion/miniapp.py`).

## Pourquoi ce sprint existe

Le gate actuel (`accord_action.py`) suppose **un tour de parole humain dans un fil de
conversation** : le « oui » est un message, le registre est en mémoire vive, et un refus est
deviné par regex. Cela ne suffit pas pour piloter des apps :

1. Un incident n'a **pas de fil** : l'alerte vient d'un collecteur, pas d'un humain qui parle.
   Le co-agent et la Gateway MCP contournent même le gate (limite déjà consignée dans l'ADR).
2. Sur Telegram, aujourd'hui, un « oui » textuel est interprété par le LLM. Pas de boutons
   Telegram natifs : `adaptateurs.py` ne gère ni `inline_keyboard` ni `callback_query`.
3. Rien n'est persistant : un redémarrage du Cœur efface les accords (sens sûr, mais inutilisable
   pour une demande qui attend ton réveil pendant 8 h).
4. Pas de niveaux de sensibilité.

## Conception

**Nouveau module `core/approbations.py`** (à côté de `accord_action.py`, qu'il ne remplace pas :
les 133 actions existantes gardent le gate conversationnel).

- **Enregistrement persistant** (SQLite du Cœur) : `id` aléatoire 128 bits, capacité, empreinte
  (même fonction `accord_action.empreinte`), résumé lisible, `sensibilite`, `origine`
  (`conversation|incident|coagent|mcp`), `statut`, dates, `decide_par`, `canal`, résultat.
- **Machine à états stricte** : `en_attente → approuvee | refusee | expiree`, puis
  `approuvee → executee | echec`. Aucune autre transition. Usage unique.
- **Consommation atomique** : `UPDATE … SET statut='executee' WHERE id=? AND statut='approuvee'
  AND expire_a>now` ; on exécute seulement si 1 ligne modifiée (double clic / double callback
  sans double exécution).
- **Niveaux** déclarés par capacité dans `manifest.json` (`"sensibilite"`) : `lecture` (aucune
  approbation), `reversible`, `donnees`, `destructif`. Capacité `action: true` sans champ :
  comportement actuel inchangé (pas de régression sur les 133 existantes).
- **Prérequis** (`donnees`) : la demande porte une liste de preuves (ex. « sauvegarde vérifiée »).
  Telegram reçoit d'abord le message **sans** bouton Approuver ; quand les preuves sont réunies, le
  message est édité pour l'afficher. (Utilisé dès S247.)
- **Garde à l'exécution** dans le chemin commun `outils.executer` : si la capacité est sensible et
  que l'origine n'est pas une conversation, exiger une approbation `approuvee` d'empreinte
  identique, sinon refuser. Cela **ferme le trou co-agent/MCP** pour ces capacités.

**Telegram** (`briques/connexion/adaptateurs.py`, `pont.py`) :
- envoi avec `reply_markup.inline_keyboard`, `callback_data = "ap:<id>:<ok|ko>"` (≤ 64 octets) ;
- sondage `getUpdates` étendu à `callback_query` (`allowed_updates`), `answerCallbackQuery`,
  `editMessageText` vers l'état final (✅ approuvée / ❌ refusée / ⌛ expirée) ;
- **autorisation par identité** : `callback_query.from.id` doit correspondre au propriétaire
  résolu via `correspondance.py` ; chat privé uniquement ; tout autre émetteur est ignoré et journalisé.

**Destructif** : le bouton Telegram ouvre la Mini App (`web_app`), qui affiche le détail complet et
exige un second geste ; l'`initData` signé (déjà validé en S77) authentifie. *Option de repli si la
Mini App pose problème : code à 6 chiffres affiché dans l'app, à saisir dans Telegram.*

**Mode attente (approche B)** : tâche d'horloge S29 qui relance les demandes en attente après X min
(paramètre) ; la page « maintenance » côté utilisateur arrive avec S246/S247 (elle exige Dokploy).

**Journal** append-only de chaque transition (qui, quand, quoi, empreinte). Réutiliser le mécanisme
de journal/audit existant du Cœur — *à identifier au démarrage* (`journal_modele.py`, brique `audit`).

## Ce que ça ne garantit pas (à écrire dans l'ADR du sprint)

- Que l'humain ait *compris* l'action : on garantit qu'il a vu le résumé exact et cliqué.
- La sécurité d'un compte Telegram compromis (le bouton hérite de ce risque). D'où le niveau
  `destructif` en Mini App, et le TTL court.
- Les capacités sans champ `sensibilite` : inchangées.

## Tests et preuves

- Machine à états (transitions interdites, expiration, rejeu, double consommation concurrente).
- Mauvais `from.id`, mauvais chat, `callback_data` forgé, id inconnu, empreinte modifiée.
- Persistance après redémarrage du Cœur.
- **Mutation testing du gate** (convention du dépôt, cf. S222) : le neutraliser doit faire échouer
  les tests de sécurité et laisser passer ceux de non-régression.
- Preuve LIVE avec le vrai bot sur le HP : regroupée en SLIVE (régime preuve Docker différé).

## Hors périmètre

Aucun outil d'exploitation d'apps (S246). Pas de page maintenance. Pas de migration des 133
actions existantes vers le nouveau système.

## Questions tranchées (2026-11-25)

1. **Propriétaire autorisé** : approbateur **explicite**, champ `approbateur: true` dans
   `correspondances.json` (posé via `POST /correspondances/approbateur`), en plus du statut
   « lié » et d'un chat privé.
2. **Destructif** : **code à 6 chiffres** affiché dans l'app, saisi dans Telegram (3 essais).
   Pas de Mini App.
3. **Expiration** : réversible 30 min, données 120 min, destructif 15 min, configurables par
   `APPROBATION_TTL_<NIVEAU>_MIN`.

## Preuve LIVE différée (SLIVE) : recette

1. Poser `APPROBATIONS_CLE` (même valeur) dans le `.env` du Cœur **et** de la brique connexion ;
   poser `TELEGRAM_WEBHOOK_SECRET` si le bot est en mode webhook (sans lui, callbacks et codes
   sont ignorés). `API_KEYS` de la brique doit contenir `CONNEXION_KEY` du Cœur.
2. Marquer son compte approbateur : `POST /correspondances/approbateur` (compte déjà lié,
   chat privé avec le bot).
3. Déclencher une capacité de test `sensibilite: reversible` : le message Telegram arrive avec
   les boutons ; clic **Approuver** → exécution → message édité en ✅.
4. Même chose avec un `destructif` : bouton → le message demande un code ; lire le code dans
   l'app (`GET /approbations/en_attente`) → le saisir dans Telegram → exécution → ✅.
5. Vérifier aussi : un autre compte (non approbateur) ne peut pas cliquer ; un refus ; une
   expiration.
