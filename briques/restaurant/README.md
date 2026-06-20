# Brique `restaurant` — commande & paiement à table par QR

Produit autonome (port **6010**) : un restaurateur crée un compte, gère un ou plusieurs
restaurants **totalement cloisonnés**, et ses clients commandent + paient à table en
scannant un QR code. Inspiré de Sunday / Skeat, mais souverain (rien ne sort vers un tiers).

## Les trois surfaces

| Surface | URL | Auth |
|---|---|---|
| **Back-office** restaurateur | `/` | compte (email + mot de passe) |
| **Cuisine** (plein écran) | `/cuisine?resto=<id>` | session du back-office |
| **Client** (ouvert par le QR) | `/carte/<code>` | aucune — le code de table fait *capability* |

## Le parcours

1. Le restaurateur compose sa **carte** (prix éditable, photo prise au téléphone,
   bascule *Disponible* pour les ruptures, *Plat du jour*) et crée ses **tables** → un
   **QR code** par table (généré **localement**, `segno`, jamais un service tiers).
2. Le client **scanne**, choisit son **prénom / numéro de siège**, commande. La commande
   part en **cuisine en temps réel** (WebSocket), étiquetée table + convive.
3. Au moment de payer, chacun règle **sa part** : en ligne (paiement **mock honnête** en
   incrément 1, marqué « démo »), ou **en espèces** validées par le restaurateur. La
   tablette et les clients voient le **« reste à payer »** bouger en direct.

## Multi-tenant (cloisonnement)

`Compte → Restaurant(s) → Tables / Plats / Commandes / Paiements`. Toute lecture/écriture
côté restaurateur exige le compte propriétaire (**fail-closed** : un restaurateur reçoit
un `404` sur le restaurant d'un autre, on ne révèle même pas son existence). Prouvé par
`test_isolation.py`.

## Paiement

Incrément 1 = **mock** assumé (aucun flux d'argent réel, libellé « démo » côté UI). Le
montant est recalculé **côté serveur** (jamais soumis par le client). Incrément suivant :
**Stripe Connect** réel (les fonds vont au restaurateur).

## Réglages (env)

| Variable | Rôle | Défaut |
|---|---|---|
| `RESTAURANT_DB` | chemin SQLite | `/data/restaurant.db` |
| `RESTAURANT_SECRET` | signature des sessions (HMAC) | dev non secret — **à définir en prod** |
| `RESTAURANT_SESSION_TTL` | durée de session (s) | `2592000` (30 j) |
| `RESTAURANT_PUBLIC_URL` | base d'URL des QR (vue du smartphone) | déduite de la requête |
| `CORS_ORIGINS` | origines navigateur autorisées (CSV) | `*` |

## Tests

```bash
python -m pytest -q   # auth, isolation multi-tenant, parcours complet, temps réel, QR
```

## Limites de l'incrément 1 (assumées)

- Paiement **mock** (pas de Stripe Connect réel) ;
- pas de pilotage par le Cœur (la brique est autonome, le branchement viendra) ;
- interface **FR / EN** (extension multilingue ultérieure).
