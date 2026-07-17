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

> **Depuis S173** : le champ `utilisateur` envoyé à `/assistant/chat` est bien lu par le
> Cœur (`contexte_tenant`) et détermine l'identité utilisée pour les appels S2S vers
> l'agenda (`X-User-Id`) — les rappels/événements créés via l'assistant sont donc
> attribués à la bonne personne, pas seulement mentionnés dans un message système. Reste
> vrai : ceci ne remplace pas un contrôle d'accès complet par utilisateur sur toutes les
> briques (agenda seulement pour l'instant), et le mapping ci-dessous sert toujours de
> point d'entrée pour ça.

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

### Web Push (S178) — notifications navigateur/PWA
Adaptateur `webpush` (`adaptateurs.py`) : `id_externe` = l'**endpoint** de l'abonnement
`PushSubscription` du navigateur, résolu dans le magasin `appareils.py`
(`appareils_webpush.json`, upsert par endpoint). Dépendance optionnelle `pywebpush` — si
absente, `configure()` renvoie `False` et l'adaptateur est simplement ignoré (repli
honnête, **pas** simulé).

`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` (ex. `mailto:admin@example.org`) —
identité du serveur push. La clé **publique** est aussi posée côté agenda
(`VAPID_PUBLIC_KEY`, même valeur) pour être servie au navigateur ; la clé **privée** ne vit
que **côté `connexion`**.

Endpoints :
- `GET /push/cle_publique` — clé publique VAPID, sans auth (publique par nature). Le front
  agenda (`/app`) l'appelle pour `pushManager.subscribe()`.
- `POST /push/appareils` `{utilisateur, appareil}` (`X-API-Key`) — enregistre l'appareil
  (upsert par endpoint) **et** le lie dans la table de correspondance
  (`reseau="webpush", id_externe=endpoint`) : il devient une cible normale de `/pousser`.
  Appelé par le relais `POST /push/appareils` de l'agenda, qui force `utilisateur` depuis
  le `sub` du token Keycloak de l'appelant (jamais depuis le corps envoyé par le
  navigateur).
- `DELETE /push/appareils` `{endpoint}` (`X-API-Key`) — retire l'appareil + délie la
  correspondance (coupure des notifs sur ce navigateur).

**Auto-purge** : si `pywebpush` échoue avec un statut `404`/`410` (abonnement mort — app
désinstallée, permission révoquée, expiration navigateur), l'adaptateur retire
automatiquement l'appareil du magasin — pas d'accumulation de cibles mortes.

## Relier un interlocuteur (consentement)

```bash
# `utilisateur` doit être le vrai sub Keycloak `calendar-app` de la personne (obtenu
# après sa 1re connexion à l'agenda /app, cf. briques/agenda/backend/README.md) — pas
# une étiquette libre : c'est ce qui permet à un rappel créé via Telegram de rejoindre
# le bon compte agenda (S173).
curl -X POST localhost:5870/correspondances \
  -H 'Content-Type: application/json' \
  -d '{"reseau":"telegram","id_externe":"123456","utilisateur":"<sub-keycloak-reel>"}'

# ou par code de liaison communiqué par l'interlocuteur :
curl -X POST localhost:5870/correspondances \
  -d '{"code":"A1B2C3","utilisateur":"<sub-keycloak-reel>"}'

curl localhost:5870/correspondances     # lister
```

## Tests

```bash
pytest          # 84 tests offline, déterministes (conftest purge tous les tokens)
```
