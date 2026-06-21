# Brique `mail` — la boîte de réception de l'assistant (entrant, lecture seule)

> **v0.1.0 — lecture seule.** L'assistant peut **lister, lire, résumer et trier** tes emails
> reçus, et **préparer un brouillon de réponse** (jamais envoyé). L'envoi (SMTP) viendra en v0.2.0.

Port **6030**. Multi-tenant (une boîte par clé API), provider-agnostique. Conçue comme les autres
briques : noyau + briques, le Cœur découvre les capacités via `manifest.json` et les expose comme
outils de l'assistant — **aucun code du Cœur à modifier**.

## Honnêteté technique
- **Défaut = mock honnête.** Sans compte connecté, la boîte est **simulée** (8 messages variés,
  étiquetés `source: "simule"`), **aucune connexion réseau**. Sert la démo, les tests et le dev.
- **IMAP réel = lecture seule stricte.** On ouvre la boîte en `readonly` et on lit avec
  `BODY.PEEK[]` : lire un mail ne le marque **pas** comme lu côté serveur, et **rien n'est jamais
  supprimé ni déplacé**.
- **Mot de passe chiffré au repos** (AES-GCM, clé = SHA-256 de `MAIL_VAULT_SECRET`). Jamais en
  clair dans une réponse, un log ou une erreur. ⚠️ Chiffrement *au repos*, pas bout-en-bout.
- **Résumé / tri.** Le tri et le score d'importance sont **heuristiques et explicables**
  (`domaine.py`, testés). Le digest en langage naturel passe par la Gateway LLM, avec un **repli
  factuel honnête** si elle est indisponible (`genere_par` dit toujours « ia » ou « local »).
- **v0.1.0 n'envoie rien.** Un brouillon est *préparé*, pas envoyé.

## Configuration (dans le `.env` racine)
| Variable | Rôle |
|---|---|
| `MAIL_KEY` | clé que le **Cœur** présente (`X-API-Key`) → identifie le tenant. Vide = dev « public ». |
| `MAIL_VAULT_SECRET` | clé de chiffrement du mot de passe IMAP. **Requise** pour connecter une vraie boîte. |
| `API_KEYS` | CSV des clés autorisées (fail-closed). Vide = dev ouvert. |
| `GATEWAY_URL` / `GATEWAY_KEY` / `GATEWAY_MODEL` | pour le résumé/brouillon (repli si absent). |

## Connecter une vraie boîte (IMAP, mot de passe d'application)
Ouvre la page **http://localhost:6030/** (back-office) et renseigne serveur / utilisateur /
**mot de passe d'application** (Gmail : Compte → Sécurité → Mots de passe des applications).
On préfère cette page au chat (le chat journalise les messages). La connexion est **vérifiée** par
une synchro immédiate ; en cas d'identifiants faux, rien n'est conservé.

## Capacités exposées à l'assistant
- `mail_lister` — la boîte triée par importance (lecture)
- `mail_lire` — le contenu complet d'un message (lecture)
- `mail_resumer` — le point sur la boîte, priorisé (lecture)
- `mail_trier` — la boîte rangée par catégorie (lecture)
- `mail_brouillon_repondre` — prépare un brouillon **non envoyé** (action)
- `mail_compte_connecter` — connecte une boîte IMAP (action ; préférer le back-office)

Tâche d'horloge : `sync-mail` (rafraîchit le cache toutes les heures, tolère l'échec).

## Tests
```bash
cd briques/mail && python -m pytest -q   # offline : domaine, isolation, parcours mock
```

## Reste à prouver LIVE (honnêteté)
Connecter un **vrai compte IMAP** (mot de passe d'app) via le back-office, puis lister/lire/résumer
de vrais mails. (Étape externe : tes identifiants.)
