# Guide — brancher l'email réel + les relances d'impayés (Forge)

> **Statut : documentation. Le code S22 est livré et prouvé _offline_** (envoi SMTP réel
> contre un serveur local, cadence J+7/15/30, anti-doublon). Ce guide = ce qu'il reste pour
> envoyer à de **vrais destinataires**. Voir `docs/sprints/S22-forge-emails-relances.md`.

## 0. À savoir avant (honnêteté technique)
- Le code d'envoi est **prouvé** (un email part vraiment, le message est correct). Ce qui
  dépend de toi : un **compte SMTP** et la **délivrabilité** (que Gmail/Outlook ne classe pas
  en spam → SPF/DKIM/DMARC sur ton domaine).
- **Deux étapes** recommandées : (1) **dev** avec un faux serveur (Mailpit) — tu vois les
  emails sans rien envoyer pour de vrai ; (2) **live** avec un vrai SMTP.
- Le **mot de passe SMTP** va au **coffre chiffré** (comme la clé Stripe en S21), pas en clair.

## 1. Dev — voir les emails sans les envoyer (Mailpit)
```bash
docker run -d --name mailpit -p 8025:8025 -p 1025:1025 axllent/mailpit
# UI : http://localhost:8025   (SMTP : localhost:1025, sans auth ni TLS)
```
Dans `briques/forge/.env` :
```bash
SMTP_HOST=host.docker.internal   # le core (Docker) joint Mailpit sur l'hôte
SMTP_PORT=1025
SMTP_SECURE=false
SMTP_STARTTLS=false              # Mailpit n'exige pas STARTTLS
SMTP_USER=                       # pas d'auth en dev
SMTP_FROM="Forge <forge@local>"
```
Recrée le core (`up -d --force-recreate forge`), puis demande à l'assistant
« envoie la facture FACT-… au client » → l'email apparaît dans **http://localhost:8025**.

## 2. Live — un vrai SMTP
### Option A — Gmail (mot de passe d'application)
1. Compte Google → **Sécurité** → active la **validation en 2 étapes**.
2. **Mots de passe des applications** → génère-en un (16 caractères).
3. `briques/forge/.env` :
   ```bash
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_SECURE=false
   SMTP_STARTTLS=true
   SMTP_USER=toncompte@gmail.com
   SMTP_FROM="Ton Entreprise <toncompte@gmail.com>"
   ```
4. **Mot de passe au coffre** (pas en clair) — via l'UI Forge (Settings → API keys →
   « SMTP (mot de passe) ») **ou** en API avec ton JWT :
   ```bash
   curl -X PUT http://localhost:8600/api/settings/api-keys/smtp \
     -H "Authorization: Bearer <TON_JWT>" -H "Content-Type: application/json" \
     -d '{"key":"<mot-de-passe-application-16c>"}'
   ```
   > Repli possible : `SMTP_PASS=…` dans `.env` (le coffre a la priorité).
5. Recrée le core. ⚠️ Gmail limite ~500 envois/jour et soigne peu la délivrabilité de masse.

### Option B — Fournisseur transactionnel (recommandé pour la délivrabilité)
Postmark / Amazon SES / Resend / Brevo donnent un hôte + identifiants SMTP et gèrent
SPF/DKIM. Même principe : `SMTP_HOST/PORT/USER` dans `.env`, **mot de passe au coffre**,
`SMTP_STARTTLS=true` (ou `SMTP_SECURE=true` sur port 465). Configure SPF/DKIM sur ton
domaine d'envoi (le fournisseur fournit les enregistrements DNS).

## 3. Vérifier puis utiliser
- **Envoyer une facture** : assistant « envoie la facture FACT-2026-… au client »
  (`forge_facture_envoyer`, confirmé) → la facture passe **`envoyée`** + email parti
  (démarre l'horloge des relances).
- **Voir qui relancer** : « qui dois-je relancer ? » (`forge_relances_apercu`, lecture,
  **n'envoie rien**) → liste les factures dues à J+7/15/30 + montant à recouvrer.
- **Lancer les relances** : « envoie les relances dues » (`forge_relances_envoyer`,
  confirmé) → envoie **une fois par niveau et par facture** (anti-doublon), journalisé.

## 4. Automatiser les relances (périodique)
Le moteur s'exécute **à la demande** aujourd'hui. Pour le rendre périodique sans rien
ajouter d'externe, appelle `POST /api/relances/impayes/executer` une fois par jour :
```bash
# cron hôte (exemple, 9h chaque jour) — nécessite un JWT de service valide
0 9 * * *  curl -s -X POST http://localhost:8600/api/relances/impayes/executer \
             -H "Authorization: Bearer $FORGE_SERVICE_JWT" >/dev/null
```
> L'anti-doublon garantit qu'un passage quotidien ne renvoie jamais deux fois le même
> niveau pour une même facture. (Brancher ce déclencheur dans la boucle proactive du Cœur
> est l'incrément suivant — dis-le-moi si tu veux que je le câble.)

## Récapitulatif — où va quoi
| Réglage | Où | Rôle |
|---|---|---|
| `SMTP_HOST/PORT/USER/FROM`, `SMTP_SECURE`, `SMTP_STARTTLS` | `.env` | connexion SMTP |
| mot de passe SMTP | **coffre chiffré** (provider `smtp`) ou `SMTP_PASS` (env, repli) | auth SMTP |
| `RELANCES_DB` | env (défaut tmp) | journal anti-doublon des relances |

## Cadence des relances (modifiable)
Par défaut **J+7** (rappel courtois), **J+15** (ferme), **J+30** (relance finale) — définie
dans `app/relances.py` (`NIVEAUX`) et `app/email.py` (`RELANCE_NIVEAUX`, textes). Ajuste seuils
et ton là si besoin.
