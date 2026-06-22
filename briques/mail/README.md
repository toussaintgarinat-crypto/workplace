# Brique `mail` — la boîte de réception de l'assistant (entrant) + réponse sur validation

> **v0.2.0 — multi-adresses, lecture + réponse.** Connecte **plusieurs boîtes** (perso, pro…) ;
> l'assistant les voit en une **boîte unifiée** et peut **lister/filtrer (catégorie, compte,
> non-lus), lire, résumer et trier** tes emails, **préparer un brouillon de réponse**, puis
> **l'envoyer une fois que tu l'as validé** (SMTP réel si la boîte est réelle ; envoi **simulé**
> honnête sinon). La lecture IMAP reste strictement en lecture seule.

Port **6030**. Multi-tenant (une boîte par clé API), provider-agnostique. Conçue comme les autres
briques : noyau + briques, le Cœur découvre les capacités via `manifest.json` et les expose comme
outils de l'assistant — **aucun code du Cœur à modifier**.

## Front-end
La brique sert un **vrai client mail** sur **http://localhost:6030/** : boîte unifiée (liste +
lecture), filtres (catégorie, compte, non-lus), recherche, résumé, réponse inline (préparer →
relire → envoyer) et gestion des comptes (modale ⚙ Comptes). Il est **embarqué dans le dashboard
du Cœur** comme onglet **« Mail »** (entre Agenda et Profil), via une iframe (`MAIL_UI_URL`). La
brique apparaît aussi dans le **Registre de briques** (carte avec son **port**).

### Rendu HTML des emails (v0.4.0)
Les emails au format **HTML** (newsletters, factures, pro… souvent *sans* version texte) sont
désormais **conservés et affichés fidèlement**, comme dans une vraie boîte mail :
- le backend garde **les deux** parties (`text/plain` *et* `text/html`) ; l'extrait est dérivé du
  HTML quand il n'y a pas de texte (fini les corps vides) ;
- le HTML est **assaini** par **DOMPurify** (vendu en local, `/static/purify.min.js`, aucun CDN)
  puis rendu dans une **`<iframe>` sandboxée** (sans `allow-scripts` : aucun JS de l'email ne
  s'exécute, et le CSS de l'email ne déborde pas dans l'app) ;
- les **images distantes sont bloquées par défaut** (protège des **pixels espions** / tracking),
  avec un bouton **« Afficher les images »** par message. Les emails en texte seul gardent leur
  rendu d'origine.

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

## Connecter ses boîtes (IMAP, mot de passe d'application) — plusieurs possibles
Ouvre la page **http://localhost:6030/** (back-office) : elle liste tes boîtes connectées et permet
d'en **ajouter plusieurs** (perso, pro…) ou d'en déconnecter une. Pour chaque boîte, renseigne
serveur / utilisateur / **mot de passe d'application** (Gmail : Compte → Sécurité → Mots de passe
des applications ; Outlook : `outlook.office365.com` ; iCloud : `imap.mail.me.com` ; Yahoo :
`imap.mail.yahoo.com`). On préfère cette page au chat (le chat journalise les messages). Chaque
connexion est **vérifiée** par une synchro immédiate ; identifiants faux → rien n'est conservé.

L'assistant voit alors une **boîte unifiée** ; on peut filtrer sur une adresse
(`mail_lister` param `compte`).

## Filtres : catégories intégrées + filtres personnalisés
La barre de filtres propose les **catégories intégrées** (Tout, Non lus, 💶 Factures, 📅 RDV,
👤 Perso, 🔔 Notifs, 📰 Newsletters, ✉️ Autres) **et tes filtres personnalisés**. Bouton
**« + Filtre »** : crée un filtre sur mesure par **mots-clés** et/ou **expéditeur** (sous-chaîne).
Pour **« les mails par entreprise »** : un filtre par société sur le **domaine d'expéditeur**
(ex. `@acme.com`). Stockés par tenant, supprimables (✕ sur le chip). API : `GET/POST/DELETE
/filtres` ; `GET /mail?filtre=<id>`.

## Répondre : préparer → valider → envoyer
1. `mail_brouillon_repondre` prépare un brouillon (avec une consigne possible) — **non envoyé**.
2. Tu le relis / l'ajustes (par le chat ou la section « Brouillons » du back-office).
3. `mail_brouillon_envoyer` l'envoie **après ton accord explicite** (action gardée). L'envoi est
   **réel** (SMTP) si le brouillon vient d'une boîte réelle ; sinon **simulé** (clairement étiqueté,
   rien ne part). Pour le réel, renseigne le serveur SMTP à la connexion (deviné depuis l'hôte IMAP
   sinon : `imap.gmail.com` → `smtp.gmail.com`, port 587 STARTTLS).

## Capacités exposées à l'assistant
- `mail_lister` — la boîte unifiée triée par importance, filtrable (catégorie, **compte**, non-lus)
- `mail_comptes_lister` — les adresses connectées (lecture)
- `mail_lire` — le contenu complet d'un message (lecture)
- `mail_resumer` — le point sur la boîte, priorisé (lecture)
- `mail_trier` — la boîte rangée par catégorie (lecture)
- `mail_brouillon_repondre` — prépare un brouillon de réponse (action)
- `mail_brouillon_envoyer` — **envoie** un brouillon validé, réel ou simulé (action à effet réel)
- `mail_compte_connecter` — ajoute une boîte IMAP/SMTP (action ; préférer le back-office)
- `mail_compte_deconnecter` — retire une boîte (action)

Tâche d'horloge : `sync-mail` (rafraîchit le cache toutes les heures, tolère l'échec).

## Tests
```bash
cd briques/mail && python -m pytest -q   # offline : domaine, isolation, parcours mock
```

## Reste à prouver LIVE (honnêteté)
Connecter un **vrai compte IMAP/SMTP** (mot de passe d'app) via le back-office, puis
lister/lire/résumer de vrais mails et **envoyer une vraie réponse** (un email part réellement).
(Étape externe : tes identifiants.)
