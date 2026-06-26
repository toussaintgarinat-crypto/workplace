# Brique `telephonie` — canal SMS & voix (multi-tenant)

Produit autonome (port **6050**), **provider-agnostique**. Donne à l'assistant un vrai
téléphone : **acheter un numéro**, **envoyer/recevoir des SMS**, **passer des appels vocaux**.
Chaque solution est isolée par sa **clé API**. **Repli honnête** : sans credentials, tout est
**simulé (mock)** et étiqueté comme tel — jamais un faux envoi présenté comme réel.

## Pourquoi cette brique (et pas AgentPhone-MCP tel quel)

[AgentPhone-MCP](https://github.com/AgentPhone-AI/agentphone-mcp) (MIT) est un **serveur MCP**
qui donne le téléphone à un agent. Or le Cœur de Workplace est **MCP _serveur_** (`core/mcp.py`),
pas **client** : il n'absorbe pas de serveur MCP externe. Le pattern natif, c'est une **brique**
dont le `manifest.json` déclare des `capacites` → le Cœur les découvre (S63/S64) et les expose
comme **outils du LLM**. On reprend donc l'**idée** d'AgentPhone (acheter un numéro / SMS / appel
en langage naturel), implémentée en brique Workplace, exactement comme `paiements`.

## Fournisseurs

| `mode` | Quoi | Config |
|---|---|---|
| `mock` | **Honnête** par défaut. Rien ne part sur le réseau, tout est étiqueté « mock ». | *(rien)* |
| `twilio` | Réel (facturé) : recherche+achat de numéro, Messages, Calls, webhooks signés. | `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` |

Le choix est automatique : credentials présents ⇒ Twilio, sinon ⇒ mock. Le token n'apparaît
**jamais** en clair (réponses, logs, erreurs). Appels REST directs en `httpx` — pas de SDK lourd.

## Endpoints / capacités (outils du Cœur)

| Route | Capacité | Rôle |
|---|---|---|
| `GET /config` | `telephonie_config` | mock ou Twilio ? (jamais le token) |
| `GET /numeros` | `telephonie_numeros` | numéros possédés par la solution |
| `POST /numeros` | `telephonie_numero_acheter` | acheter un numéro (SMS+voix) |
| `GET /sms` | `telephonie_sms_lister` | SMS envoyés/reçus |
| `POST /sms` | `telephonie_sms_envoyer` | envoyer un SMS (émetteur possédé) |
| `GET /appels` | `telephonie_appels_lister` | appels passés |
| `POST /appels` | `telephonie_appel_passer` | appel vocal (message énoncé en TwiML `<Say>`) |
| `POST /webhooks/twilio` | — | SMS entrant (signature `X-Twilio-Signature` vérifiée) |

Les **actions** (achat, SMS, appel) passent le **gate `confirme=true`** imposé par le Cœur :
l'assistant doit confirmer avant qu'un SMS/appel parte. Cloisonnement : on ne peut émettre que
depuis un numéro **possédé** par la solution (sinon `409`).

## Cloisonnement multi-tenant

La clé API (`X-API-Key` ou `Bearer`) identifie la **solution** ; le tenant stocké est son
**empreinte** sha256 tronquée (la clé reste secrète). `API_KEYS` (CSV) défini ⇒ fail-closed ;
vide ⇒ dev ouvert (espace « public »). Numéros, messages et appels sont rangés par solution.

## Tests

```bash
pytest        # 18 tests offline (domaine pur + parcours mock + isolation), sans réseau ni clé
```

## Configuration (réel)

```bash
export TWILIO_ACCOUNT_SID=ACxxxxxxxx
export TWILIO_AUTH_TOKEN=xxxxxxxx
export TWILIO_FROM=+33757000000        # affiché par /config (optionnel)
uvicorn main:app --host 0.0.0.0 --port 6050
```

`GET /config` indique honnêtement `mock` ou `twilio`. Tant que rien n'est branché, tout est
**simulé** et la brique le **dit**.

## Reste à prouver LIVE

- Achat de numéro / SMS / appel **réels** Twilio (clé test puis production = étape externe).
- Webhook entrant : exposer `/webhooks/twilio` en HTTPS (cf. tunnels cloudflared) et configurer
  l'URL dans la console Twilio du numéro.
- Synergie : brancher l'assistant (rappels, confirmations de RDV par SMS) et le restaurant
  (notifier une table). Le bémol assumé : Twilio est un backend **payant**.
