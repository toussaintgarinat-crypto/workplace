# S245 — Socle d'approbation Telegram

Épopée : [livraison + support](EPOPEE-livraison-support-assistant.md). Statut : **spécifié, non codé**.
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

## Questions à trancher au démarrage

1. Où stocker le propriétaire Telegram autorisé : `correspondance.py` suffit-il, ou faut-il un champ « approbateur » explicite ?
2. Mini App ou code à 6 chiffres pour `destructif` ?
3. Durée d'expiration par niveau (proposition : réversible 30 min, données 2 h, destructif 15 min).
