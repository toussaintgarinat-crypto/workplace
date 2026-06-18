# Brique `connexion` — parler à l'assistant depuis ses messageries

Pont **bidirectionnel** entre les messageries du quotidien (Telegram, WhatsApp, Discord,
et plus tard SMS/email) et l'**assistant du Cœur** (`POST :5100/assistant/chat`, flux SSE,
stateless).

- **Provider-agnostique** : un adaptateur branchable par réseau (`adaptateurs.py`), même
  esprit que les fournisseurs de la brique images. Un réseau non configuré est simplement
  ignoré — **repli honnête, jamais simulé**.
- **Multi-utilisateur avec consentement** : chaque interlocuteur externe est rattaché à un
  utilisateur Workplace (`correspondance.py`). Par défaut un inconnu **ne traverse pas** :
  il reçoit un *code de liaison* qu'un administrateur valide via `/correspondances`.
- **Historique persisté par interlocuteur** (`conversations.py`) : l'assistant étant
  stateless, c'est la brique qui tient le fil de chaque conversation (fenêtre bornée).

> ⚠️ **Limite honnête (v0.1.0).** `/assistant/chat` n'isole pas les permissions par
> utilisateur (pas de paramètre d'utilisateur, identité globale). Le mapping multi-utilisateur
> sert au routage / journal / consentement **côté brique**, et on injecte un message *système*
> « qui parle » au début de chaque conversation. Une vraie isolation par utilisateur côté
> noyau est un sprint ultérieur.

## Lancer

```bash
docker compose up -d
curl localhost:5870/sante        # réseaux connus / configurés / assistant joignable ?
```

Tout se configure par variables d'environnement (à poser dans le `.env` racine, **aucun
secret en dur**). En dev, `CONNEXION_OUVERT=1` autorise tout le monde (rattaché à
`CONNEXION_UTILISATEUR_DEFAUT`).

## Réseaux

### Telegram — le plus simple (preuve LIVE ciblée, aucune URL publique requise)
1. Crée un bot via **@BotFather**, récupère le token → `TELEGRAM_BOT_TOKEN`.
2. La brique tire les messages par `getUpdates` : `POST :5870/sonder/telegram` (ou laisse
   l'**horloge S29** appeler la tâche `poll-telegram` du manifest).
3. Envoie un message au bot depuis ton téléphone → la réponse de l'assistant revient dans
   Telegram. *(Webhook signé aussi possible via `setWebhook` + `TELEGRAM_WEBHOOK_SECRET`.)*

### WhatsApp — Cloud API officielle (Meta)
`WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`.
Webhook Meta → `GET/POST :5870/webhook/whatsapp` (vérification `hub.challenge` + corps signé
HMAC `X-Hub-Signature-256`). Demande un compte Meta Business.

### Discord — interactions signées Ed25519
`DISCORD_PUBLIC_KEY`, `DISCORD_BOT_TOKEN`. Endpoint d'interactions →
`POST :5870/webhook/discord` (signature Ed25519 vérifiée, PING→PONG géré).
*Note : les messages privés hors slash-commands passent par la passerelle Gateway
(websocket), non couverte ici — extension prévue.*

### Email / SMS — squelette honnête
`EMAILSMS_FOURNISSEUR` (à brancher : SMTP entrant, Twilio…). Non configuré → ignoré.

## Relier un interlocuteur (consentement)

```bash
# par (réseau, id) :
curl -X POST localhost:5870/correspondances \
  -H 'Content-Type: application/json' \
  -d '{"reseau":"telegram","id_externe":"123456","utilisateur":"toi@workplace"}'

# ou par code de liaison communiqué par l'interlocuteur :
curl -X POST localhost:5870/correspondances \
  -d '{"code":"A1B2C3","utilisateur":"toi@workplace"}'

curl localhost:5870/correspondances     # lister
```

## Tests

```bash
pytest          # 44 tests offline, déterministes (conftest purge tous les tokens)
```
