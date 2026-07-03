# Sprint S139 — CORS hardening : restreindre les origines autorisées en production

> **But du sprint** : remplacer le `CORS_ORIGINS=*` par défaut (accepté partout, y compris
> sur le HP Proxmox) par des valeurs concrètes par environnement. Aujourd'hui, 13+ briques
> acceptent des requêtes de n'importe quelle origine navigateur. Un site malveillant ouvert
> par l'utilisateur peut appeler les APIs si la personne est connectée.

- **Sprint** : S139
- **Catégorie** : Sécurité / configuration
- **Statut** : ✅ LIVRÉ (2026-07-03)
- **Date de planification** : 2026-07-03
- **Date de livraison** : 2026-07-03
- **Briques concernées** : calcul, studio, restaurant, video, telephonie, transcription, images, mail, recherche, connexion, voix, personnages, paiements, dev, synopsis, oria, peertube-wrapper

---

## Contexte

Chaque brique FastAPI charge ses origines autorisées ainsi :

```python
_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])
```

Le `.env.example` racine contient `CORS_ORIGINS=*` (non commenté, ligne 15). Résultat :
- En **dev local** : acceptable (mono-poste, pas d'accès réseau externe).
- Sur le **HP Proxmox** (accès distant) : toutes les APIs sont accessibles depuis n'importe
  quelle origine, y compris des pages web tierces.

Deux briques font déjà bien : `agenda` (`http://localhost:5100,http://localhost:3000`) et
`forge` (valeur concrète dans le compose prod). Ce sont les modèles à suivre.

---

## Chantiers

### C0 — Documenter les origines légitimes par environnement

Identifier les origines qui appellent réellement chaque brique :
- **Dashboard Cœur** → `http://localhost:5100` (dev) / `https://workplace.ton-domaine.fr` (prod)
- **Apps générées** → variable (`localhost:*` en dev, domaine en prod)
- **Oria frontend** → `http://localhost:3003` (dev) / `https://oria.ton-domaine.fr` (prod)

Livrable : tableau des origines par contexte (dev / HP / prod publique).

### C1 — Mettre à jour `.env` et `.env.example` racine

```diff
# .env.example (ligne 15)
- CORS_ORIGINS=*
+ # Dev local : laisser * ou lister les ports utilisés
+ # CORS_ORIGINS=http://localhost:5100,http://localhost:3003,http://localhost:3000
+ # HP Proxmox : lister uniquement les origines de confiance
+ CORS_ORIGINS=http://localhost:5100,http://localhost:3003
```

Pour le `.env` réel du HP, utiliser les vraies URLs :
```
CORS_ORIGINS=http://192.168.1.89:5100,http://192.168.1.89:3003
```

### C2 — Ajouter CORS_ORIGINS aux docker-compose qui ne le propagent pas

Certaines briques n'ont pas encore `CORS_ORIGINS` dans leur `environment:`. Vérifier :

```bash
grep -rL "CORS_ORIGINS" /Users/garinat_t/Desktop/Workplace/briques/*/docker-compose.yml
```

Pour chaque brique manquante, ajouter :
```yaml
environment:
  - CORS_ORIGINS=${CORS_ORIGINS:-http://localhost:5100}
```

### C3 — Valider que `allow_methods=["*"]` est acceptable

Le CORS actuel autorise toutes les méthodes HTTP (`GET`, `POST`, `DELETE`, `PATCH`…).
Pour les briques qui n'exposent que `GET` (ex. `recherche`), restreindre à `["GET", "POST"]`
est une bonne pratique supplémentaire, mais ce n'est pas l'urgence principale.

Décision : faire dans un second temps, après C1/C2.

---

## Critère d'acceptation

- `CORS_ORIGINS=*` commenté (ou supprimé) du `.env.example` racine
- Le `.env` du HP contient des origines explicites
- Aucune brique en production n'accepte l'origine `*`
- Test : ouvrir la console navigateur depuis une URL étrangère et vérifier que les appels
  XHR vers les APIs retournent une erreur CORS (pas de header `Access-Control-Allow-Origin`)

---

## Effort estimé

**0,5 journée.** Principalement de la configuration, pas de code.

## Risque si non fait

Un site malveillant (phishing, pub) ouvert dans le navigateur d'un utilisateur connecté
au HP peut lire les données de toutes les briques via XHR silencieux.
